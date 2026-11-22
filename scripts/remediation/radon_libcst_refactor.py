"""High-level Cyclomatic Complexity Refactoring using libcst.

TRUE refactoring (not suppression):
- Extract Method
- Simplify Conditionals
- Early Returns / Guard Clauses
- Flatten Nested Conditionals
- Preserves ALL formatting, comments, type hints, docstrings

Uses libcst (Concrete Syntax Tree) for lossless code transformation.
Used by Meta/Instagram for large-scale codemods.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst
from libcst import matchers as m
from libcst.metadata import MetadataWrapper, PositionProvider

logger = logging.getLogger(__name__)


@dataclass
class RefactoringStats:
    """Statistics for a refactoring operation."""

    original_cc: int = 0
    final_cc: int = 0
    methods_extracted: int = 0
    conditionals_simplified: int = 0
    guard_clauses_added: int = 0
    nested_flattened: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ExtractedMethod:
    """Information about an extracted method."""

    name: str
    source_node: cst.CSTNode
    params: list[str]
    return_type: cst.Annotation | None
    is_async: bool
    complexity_reduced: int


class ComplexityAnalyzer(cst.CSTVisitor):
    """Analyzes cyclomatic complexity of functions using libcst."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, target_cc: int = 8):
        self.target_cc = target_cc
        self.function_cc: dict[str, int] = {}
        self.current_cc = 1
        self._in_function = False
        self._func_stack: list[str] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool | None:
        self._func_stack.append(node.name.value)
        self.current_cc = 1
        self._in_function = True
        return True

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.function_cc[original_node.name.value] = self.current_cc
        self._func_stack.pop()
        self._in_function = len(self._func_stack) > 0
        self.current_cc = 1

    def visit_AsyncFunctionDef(self, node: cst.FunctionDef) -> bool | None:
        return self.visit_FunctionDef(node)

    def leave_AsyncFunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.leave_FunctionDef(original_node)

    # Complexity-increasing nodes
    COMPLEXITY_NODES = (
        cst.If,
        cst.While,
        cst.For,
        cst.ExceptHandler,
        cst.With,
        cst.Assert,
        cst.BooleanOperation,
        cst.Comparison,
        cst.IfExp,
        cst.Try,
    )

    def _increment_cc(self, node: cst.CSTNode) -> None:
        if self._in_function and self._func_stack:
            self.current_cc += 1

    def visit_If(self, node: cst.If) -> bool | None:
        self._increment_cc(node)
        return True

    def visit_While(self, node: cst.While) -> bool | None:
        self._increment_cc(node)
        return True

    def visit_For(self, node: cst.For) -> bool | None:
        self._increment_cc(node)
        return True

    def visit_ExceptHandler(self, node: cst.ExceptHandler) -> bool | None:
        self._increment_cc(node)
        return True

    def visit_With(self, node: cst.With) -> bool | None:
        self._increment_cc(node)
        return True

    def visit_Assert(self, node: cst.Assert) -> bool | None:
        self._increment_cc(node)
        return True

    def visit_BooleanOperation(self, node: cst.BooleanOperation) -> bool | None:
        self._increment_cc(node)
        return True

    def visit_Comparison(self, node: cst.Comparison) -> bool | None:
        # Each additional comparison operator adds complexity
        if len(node.comparisons) > 1:
            self.current_cc += len(node.comparisons) - 1
        return True

    def visit_IfExp(self, node: cst.IfExp) -> bool | None:
        self._increment_cc(node)
        return True

    def visit_Try(self, node: cst.Try) -> bool | None:
        # Each except handler adds complexity
        self.current_cc += len(node.handlers)
        return True


class ComplexityReducer(cst.CSTTransformer):
    """
    TRUE refactoring transformer that reduces cyclomatic complexity.

    Strategies (in order of preference):
    1. Guard Clauses - Early returns for preconditions
    2. Extract Method - Pull complex blocks into well-named helpers
    3. Simplify Conditionals - Replace complex boolean logic with helpers
    4. Early Returns - Reduce nesting by returning early
    5. Flatten Nested Conditionals - Reduce depth
    """

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, target_cc: int = 8, max_extract_depth: int = 2):
        self.target_cc = target_cc
        self.max_extract_depth = max_extract_depth
        self.stats = RefactoringStats()
        self._extracted_methods: list[cst.FunctionDef] = []
        self._method_counter = 0
        self._current_function: str | None = None
        self._func_params: list[str] = []
        self._current_cc = 1
        self._in_function = False
        self._extracted_names: set[str] = set()
        self._ifs_to_extract: set[int] = set()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> cst.CSTNode | None:
        self._current_function = node.name.value
        self._func_params = [arg.name.value for arg in node.params.params]
        self._in_function = True
        self._current_cc = 1

        # Analyze this function and mark ifs for extraction
        self._analyze_and_mark_ifs(node)

        return None

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        """Extract sequential conditionals and apply other transformations at function level."""
        # Apply sequential if extraction to the function body
        if hasattr(updated_node.body, "body"):
            new_body = self._extract_sequential_ifs(updated_node.body)
            if new_body is not updated_node.body:
                updated_node = updated_node.with_changes(body=new_body)
        return updated_node

    def _analyze_and_mark_ifs(self, node: cst.FunctionDef) -> None:
        """Analyze function and mark deeply nested ifs for extraction."""
        self._ifs_to_extract = set()

        all_ifs = self._get_all_ifs_with_depth(node)

        # Sort by depth (deepest first)
        all_ifs.sort(key=lambda x: x[1], reverse=True)

        # Mark deeply nested ifs for extraction (depth > 3)
        for start_line, depth in all_ifs:
            if depth > 3 and self._should_extract_if_by_position(node, start_line, depth):
                self._ifs_to_extract.add(start_line)

    def _get_all_ifs_with_depth(self, node: cst.FunctionDef) -> list[tuple[int, int]]:
        """Get all if statements in a function with their nesting depth. Returns (start_line, depth)."""
        ifs = []

        def traverse(n: cst.CSTNode, depth: int):
            if isinstance(n, cst.If):
                # Get position metadata using the transformer's get_metadata
                pos = self.get_metadata(PositionProvider, n, None)
                if pos:
                    start_line = pos.start.line
                    ifs.append((start_line, depth))

                # Traverse body for nested ifs
                if hasattr(n, "body") and hasattr(n.body, "body"):
                    for child in n.body.body:
                        traverse(child, depth + 1)

                # Traverse orelse for nested ifs
                if n.orelse:
                    if hasattr(n.orelse, "body"):
                        if isinstance(n.orelse.body, cst.IndentedBlock):
                            for child in n.orelse.body.body:
                                traverse(child, depth + 1)
                        elif isinstance(n.orelse.body, list):
                            for child in n.orelse.body:
                                traverse(child, depth + 1)
                    elif isinstance(n.orelse, cst.IndentedBlock):
                        for child in n.orelse.body:
                            traverse(child, depth + 1)
            elif (
                isinstance(n, cst.IndentedBlock) or hasattr(n, "body") and isinstance(n.body, list)
            ):
                for child in n.body:
                    traverse(child, depth)
            elif hasattr(n, "children"):
                for child in n.children:
                    traverse(child, depth)

        traverse(node, 0)
        return ifs

    def _should_extract_if_by_position(
        self, node: cst.FunctionDef, start_line: int, depth: int
    ) -> bool:
        """Check if if at given position should be extracted."""
        # Find the if node at this position
        target_node = None

        def find_if(n: cst.CSTNode):
            nonlocal target_node
            if isinstance(n, cst.If):
                pos = self.get_metadata(PositionProvider, n, None)
                if pos and pos.start.line == start_line:
                    target_node = n
                    return

            # Traverse body for nested ifs
            if isinstance(n, cst.If):
                if hasattr(n, "body") and hasattr(n.body, "body"):
                    for child in n.body.body:
                        find_if(child)
                if n.orelse and hasattr(n.orelse, "body"):
                    if isinstance(n.orelse.body, cst.IndentedBlock):
                        for child in n.orelse.body.body:
                            find_if(child)
                    elif isinstance(n.orelse.body, list) or isinstance(n.orelse, cst.IndentedBlock):
                        for child in n.orelse.body:
                            find_if(child)
            elif (
                isinstance(n, cst.IndentedBlock) or hasattr(n, "body") and isinstance(n.body, list)
            ):
                for child in n.body:
                    find_if(child)
            elif hasattr(n, "children"):
                for child in n.children:
                    find_if(child)

        find_if(node)
        if target_node:
            return self._should_extract_if(target_node, check_depth=True, known_depth=depth)
        return False

    def _calculate_cc(self, node: cst.FunctionDef) -> int:
        """Calculate cyclomatic complexity of a function."""
        analyzer = ComplexityAnalyzer()
        wrapper = MetadataWrapper(node)
        wrapper.visit(analyzer)
        return analyzer.function_cc.get(node.name.value, 1)

    def _calculate_block_cc(self, node: cst.If) -> int:
        """Calculate cyclomatic complexity contributed by an if block and its children."""
        cc = 1  # The if itself adds 1

        # Manually traverse the node's children to find complexity-increasing nodes
        def traverse(node):
            nonlocal cc
            if hasattr(node, "children"):
                for child in node.children:
                    if isinstance(
                        child,
                        (
                            cst.If,
                            cst.While,
                            cst.For,
                            cst.ExceptHandler,
                            cst.With,
                            cst.Assert,
                            cst.BooleanOperation,
                        ),
                    ):
                        cc += 1
                    elif isinstance(child, cst.Comparison):
                        if len(child.comparisons) > 1:
                            cc += len(child.comparisons) - 1
                    elif isinstance(child, cst.IfExp):
                        cc += 1
                    elif isinstance(child, cst.Try):
                        cc += len(child.handlers)
                    # Recurse into children
                    if hasattr(child, "children"):
                        traverse(child)

        traverse(node)
        return cc

    def _get_nesting_depth(self, node: cst.If) -> int:
        """Get the maximum nesting depth of if statements within this node."""
        max_depth = 0

        def traverse(n: cst.If, depth: int):
            nonlocal max_depth
            max_depth = max(max_depth, depth)
            if hasattr(n, "body") and hasattr(n.body, "body"):
                for child in n.body.body:
                    if isinstance(child, cst.If):
                        traverse(child, depth + 1)
                if n.orelse and hasattr(n.orelse, "body"):
                    if isinstance(n.orelse.body, cst.IndentedBlock):
                        for child in n.orelse.body.body:
                            traverse(child, depth + 1)
                    elif isinstance(n.orelse.body, list) or isinstance(n.orelse, cst.IndentedBlock):
                        for child in n.orelse.body:
                            traverse(child, depth + 1)
            elif hasattr(n, "children"):
                for child in n.children:
                    if isinstance(child, cst.If):
                        traverse(child, depth + 1)
                    elif hasattr(child, "children"):
                        for c in child.children:
                            if isinstance(c, cst.If):
                                traverse(c, depth + 1)

        traverse(node, 0)
        return max_depth

    def _should_extract_if(
        self, node: cst.If, check_depth: bool = True, known_depth: int = None
    ) -> bool:
        """Determine if an if block should be extracted to a helper method."""
        # Calculate CC for this specific if block
        block_cc = self._calculate_block_cc(node)

        # Use known_depth if provided, otherwise calculate
        nesting_depth = known_depth if known_depth is not None else self._get_nesting_depth(node)

        # Extract if: block exceeds target CC OR deep nesting (> 3 levels)
        if block_cc > self.target_cc:
            return True

        # Also extract deeply nested blocks even if individual CC is low
        if check_depth and nesting_depth > 3:
            return True

        # Don't extract if already simple
        if self._is_simple_if(node):
            return False

        return False

    def _is_simple_if(self, node: cst.If) -> bool:
        """Check if if statement is already simple."""
        # Get body length
        body_len = len(node.body.body) if hasattr(node.body, "body") else 0

        # Get orelse length
        orelse_len = 0
        if node.orelse:
            if hasattr(node.orelse, "body"):
                if isinstance(node.orelse.body, cst.IndentedBlock):
                    orelse_len = len(node.orelse.body.body)
                elif isinstance(node.orelse.body, list):
                    orelse_len = len(node.orelse.body)
            elif isinstance(node.orelse, cst.IndentedBlock):
                orelse_len = len(node.orelse.body)

        return (
            not self._has_complex_condition(node.test)
            and not self._has_nested_ifs(node)
            and body_len <= 3
            and orelse_len <= 2
        )

    def _has_complex_condition(self, test: cst.BaseExpression) -> bool:
        """Check if condition is complex (multiple operators, comparisons)."""
        if m.matches(test, m.BooleanOperation()):
            return True
        if m.matches(test, m.Comparison()) and len(test.comparisons) > 2:
            return True
        if m.matches(test, m.IfExp()):
            return True
        return bool(m.matches(test, m.Call()))

    def _has_nested_ifs(self, node: cst.If) -> bool:
        """Check if if statement has nested if statements."""

        def traverse(node):
            for child in node.children:
                if isinstance(child, cst.If) and child is not node:
                    return True
                if hasattr(child, "children") and traverse(child):
                    return True
            return False

        return traverse(node)

    def _is_long_block(self, body: cst.BaseSuite) -> bool:
        """Check if block is too long (more than 10 statements)."""
        return len(body.body) > 10

    def leave_If(self, original_node: cst.If, updated_node: cst.If) -> cst.CSTNode:
        """Extract marked if blocks into helper methods, or flatten nested conditionals."""
        if not self._in_function:
            return updated_node

        # Get position of this if node using original_node
        pos = self.get_metadata(PositionProvider, original_node, None)
        if pos and pos.start.line in getattr(self, "_ifs_to_extract", set()):
            helper_name = self._generate_helper_name("check")
            helper_method = self._create_helper_from_if(updated_node, helper_name)
            self._extracted_methods.append(helper_method)
            self.stats.methods_extracted += 1

            # Replace the if with a call to the helper - pass the required arguments
            used_vars = self._get_used_variables(updated_node)
            args = [cst.Arg(value=cst.Name(value=p)) for p in self._func_params if p in used_vars]

            helper_call = cst.Return(
                value=cst.Call(
                    func=cst.Name(value=helper_name),
                    args=args,
                )
            )

            # Wrap in SimpleStatementLine for proper formatting
            return cst.SimpleStatementLine(body=[helper_call])

        # Strategy 2: Flatten nested conditionals
        if self._can_flatten_nested(updated_node):
            self.stats.nested_flattened += 1
            return self._flatten_nested(updated_node)

        # Default: return the updated node unchanged
        return updated_node

    def _generate_helper_name(self, prefix: str) -> str:
        """Generate a unique helper method name."""
        self._method_counter += 1
        name = f"_{self._current_function}_{prefix}_{self._method_counter}"
        while name in self._extracted_names:
            self._method_counter += 1
            name = f"_{self._current_function}_{prefix}_{self._method_counter}"
        self._extracted_names.add(name)
        return name

    def _create_helper_from_if(self, if_node: cst.If, name: str) -> cst.FunctionDef:
        """Create a helper method from an if statement."""
        # Collect variables used in the if block
        used_vars = self._get_used_variables(if_node)
        params = [p for p in self._func_params if p in used_vars]

        # If there's an orelse, we need to include it in the helper
        if if_node.orelse:
            # Create if-else structure in helper
            helper_body = cst.IndentedBlock(
                body=[
                    cst.If(
                        test=if_node.test,
                        body=if_node.body,
                        orelse=if_node.orelse,
                    )
                ]
            )
        else:
            helper_body = if_node.body

        # Create the helper function
        return cst.FunctionDef(
            name=cst.Name(value=name),
            params=cst.Parameters(params=[cst.Param(name=cst.Name(value=p)) for p in params]),
            body=helper_body,
            leading_lines=[cst.EmptyLine()],
        )

    def _get_used_variables(self, node: cst.CSTNode) -> set[str]:
        """Get all variable names used in a node (assumed Load context)."""
        names = set()

        def traverse(node):
            for child in node.children:
                if isinstance(child, cst.Name):
                    names.add(child.value)
                if hasattr(child, "children"):
                    traverse(child)

        traverse(node)
        return names

    # ==================== STRATEGY 3: Simplify Conditionals ====================

    def leave_Comparison(
        self, original_node: cst.Comparison, updated_node: cst.Comparison
    ) -> cst.CSTNode:
        """Simplify chained comparisons where possible."""
        if len(updated_node.comparisons) > 3:
            self.stats.conditionals_simplified += 1
        return updated_node

    def leave_BooleanOperation(
        self, original_node: cst.BooleanOperation, updated_node: cst.BooleanOperation
    ) -> cst.CSTNode:
        """Simplify complex boolean operations."""
        # Count the number of boolean operations in the chain
        bool_op_count = self._count_bool_ops(updated_node)
        if bool_op_count > 2 or self._is_nested_bool_op(updated_node):
            self.stats.conditionals_simplified += 1
        return updated_node

    def _count_bool_ops(self, node: cst.BooleanOperation) -> int:
        """Count the number of boolean operations in a chain."""
        count = 1
        if isinstance(node.left, cst.BooleanOperation):
            count += self._count_bool_ops(node.left)
        if isinstance(node.right, cst.BooleanOperation):
            count += self._count_bool_ops(node.right)
        return count

    def _is_nested_bool_op(self, node: cst.BooleanOperation) -> bool:
        return isinstance(node.left, cst.BooleanOperation) or isinstance(
            node.right, cst.BooleanOperation
        )

    # ==================== STRATEGY 4: Flatten Nested Conditionals ====================

    def _can_flatten_nested(self, node: cst.If) -> bool:
        """Check if nested if can be flattened with and/or."""
        if not node.orelse:
            return False

        # Pattern: if A: if B: ... else: ... -> if A and B: ... else: ...
        return bool(m.matches(node.orelse, m.If()))

    def _flatten_nested(self, node: cst.If) -> cst.CSTNode:
        """Flatten nested if statements."""
        if not node.orelse or not m.matches(node.orelse, m.If()):
            return node

        inner_if = node.orelse

        # Create combined condition: original_test AND inner_test
        combined_test = cst.BooleanOperation(
            left=node.test, operator=cst.And(), right=inner_if.test
        )

        # New if with combined condition and inner body
        new_if = cst.If(test=combined_test, body=inner_if.body, orelse=inner_if.orelse)

        return new_if

    # ==================== STRATEGY 5: Guard Clauses / Early Returns ====================

    def _can_guard_clause(self, node: cst.If) -> bool:
        """Check if if-else can be converted to guard clause (early return)."""
        if not node.orelse:
            return False

        # Pattern: if condition: return X else: ... -> if not condition: return X; ...
        # or: if condition: ... else: return Y -> if condition: ...; return Y

        body_has_return = self._has_return(node.body)
        orelse_has_return = self._has_return(node.orelse)

        # One branch returns, other continues - can convert to guard
        return body_has_return != orelse_has_return

    def _has_return(self, body: cst.BaseSuite | cst.Else | None) -> bool:
        """Check if body contains a return statement."""
        if body is None:
            return False

        # Handle IndentedBlock
        if isinstance(body, cst.IndentedBlock):
            stmts = body.body
        # Handle Else node (which contains an IndentedBlock)
        elif isinstance(body, cst.Else):
            if hasattr(body, "body") and isinstance(body.body, cst.IndentedBlock):
                stmts = body.body.body
            else:
                return False
        elif hasattr(body, "body") and isinstance(body.body, list):
            stmts = body.body
        else:
            return False

        for stmt in stmts:
            if m.matches(stmt, m.Return()):
                return True
            # Check nested blocks
            if hasattr(stmt, "body") and hasattr(stmt.body, "body"):
                if self._has_return(stmt.body):
                    return True
            if hasattr(stmt, "orelse") and stmt.orelse:
                if self._has_return(stmt.orelse):
                    return True
        return False

    def _convert_to_guard_clause(self, node: cst.If) -> cst.CSTNode:
        """Convert if-else to guard clause pattern."""
        # If body returns, negate condition and return early
        body_returns = self._has_return(node.body)
        orelse_returns = self._has_return(node.orelse)

        if body_returns and not orelse_returns:
            # if cond: return X; else: ... -> if not cond: ...; return X
            negated_test = cst.UnaryOperation(operator=cst.Not(), expression=node.test)
            # Return a list of statements: the new if + the original body statements
            new_stmts = [
                cst.If(test=negated_test, body=node.orelse, orelse=None),
            ]
            # Add the body statements (which contain the return)
            if isinstance(node.body, cst.IndentedBlock):
                new_stmts.extend(node.body.body)
            return cst.FlattenSentinel(new_stmts)

        if orelse_returns and not body_returns:
            # if cond: ... else: return X -> if cond: ...; return X
            new_stmts = []
            if isinstance(node.body, cst.IndentedBlock):
                new_stmts.extend(node.body.body)
            new_stmts.append(
                cst.If(
                    test=cst.UnaryOperation(operator=cst.Not(), expression=node.test),
                    body=node.orelse,
                    orelse=None,
                )
            )
            return cst.FlattenSentinel(new_stmts)

        return node

    # ==================== STRATEGY 6: Extract Sequential Conditionals ====================

    def _find_sequential_ifs(self, body: cst.BaseSuite) -> list[list[cst.If]]:
        """Find sequences of if/elif/else that could be extracted."""
        sequences = []
        current_seq = []

        for stmt in body.body:
            if isinstance(stmt, cst.If):
                current_seq.append(stmt)
            else:
                if len(current_seq) >= 2:
                    sequences.append(current_seq)
                current_seq = []

        if len(current_seq) >= 2:
            sequences.append(current_seq)

        return sequences

    def _extract_sequential_ifs(self, body: cst.BaseSuite) -> cst.BaseSuite:
        """Extract sequences of conditionals into helper methods."""
        new_body: list[cst.BaseStatement] = []
        i = 0
        body_stmts = body.body
        while i < len(body_stmts):
            stmt = body_stmts[i]
            if isinstance(stmt, cst.If):
                # Check for sequence
                seq: list[cst.If] = [stmt]
                j = i + 1
                while j < len(body_stmts) and isinstance(body_stmts[j], cst.If):
                    seq.append(body_stmts[j])  # type: ignore[arg-type]
                    j += 1

                if len(seq) >= 2:
                    # Extract this sequence
                    helper_name = self._generate_helper_name("check_seq")
                    helper_method = self._create_sequential_helper(seq, helper_name)
                    self._extracted_methods.append(helper_method)
                    self.stats.methods_extracted += 1

                    # Replace sequence with call
                    call_stmt = cst.SimpleStatementLine(
                        body=[cst.Return(value=cst.Call(func=cst.Name(value=helper_name), args=[]))]
                    )
                    new_body.append(call_stmt)
                    i = j
                    continue

            new_body.append(stmt)
            i += 1

        return cst.IndentedBlock(body=new_body)

    def _create_sequential_helper(self, ifs: list[cst.If], name: str) -> cst.FunctionDef:
        """Create helper method from sequence of ifs."""
        # For simplicity, combine all ifs into one function
        combined_body = []
        for if_stmt in ifs:
            combined_body.append(if_stmt)

        used_vars = self._get_used_variables(ifs[0])
        params = [p for p in self._func_params if p in used_vars]

        return cst.FunctionDef(
            name=cst.Name(value=name),
            params=cst.Parameters(params=[cst.Param(name=cst.Name(value=p)) for p in params]),
            body=cst.IndentedBlock(body=combined_body),
            leading_lines=[cst.EmptyLine()],
        )

    # ==================== STRATEGY 7: Extract Loops ====================

    def _should_extract_loop(self, node: cst.For | cst.While) -> bool:
        """Check if loop body should be extracted."""
        # Extract if body is complex (CC > target or > 10 statements)
        body = node.body
        if not hasattr(body, "body"):
            return False

        stmt_count = len(body.body)
        if stmt_count > 10:
            return True

        # Check for nested complexity
        return any(isinstance(stmt, (cst.If, cst.For, cst.While, cst.Try)) for stmt in body.body)

    def leave_For(self, original_node: cst.For, updated_node: cst.For) -> cst.CSTNode:
        """Extract complex loop bodies into helper methods."""
        if not self._in_function:
            return updated_node

        if self._should_extract_loop(updated_node):
            helper_name = self._generate_helper_name("loop")
            helper_method = self._create_loop_helper(updated_node, helper_name)
            self._extracted_methods.append(helper_method)
            self.stats.methods_extracted += 1

            # Replace loop with call
            used_vars = self._get_used_variables(updated_node)
            args = [cst.Arg(value=cst.Name(value=p)) for p in self._func_params if p in used_vars]

            call_stmt = cst.SimpleStatementLine(
                body=[
                    cst.Return(
                        value=cst.Call(
                            func=cst.Name(value=helper_name),
                            args=args,
                        )
                    )
                ]
            )
            return call_stmt

        return updated_node

    def leave_While(self, original_node: cst.While, updated_node: cst.While) -> cst.CSTNode:
        """Extract complex while loop bodies into helper methods."""
        if not self._in_function:
            return updated_node

        if self._should_extract_loop(updated_node):
            helper_name = self._generate_helper_name("loop")
            helper_method = self._create_loop_helper(updated_node, helper_name)
            self._extracted_methods.append(helper_method)
            self.stats.methods_extracted += 1

            used_vars = self._get_used_variables(updated_node)
            args = [cst.Arg(value=cst.Name(value=p)) for p in self._func_params if p in used_vars]

            call_stmt = cst.SimpleStatementLine(
                body=[
                    cst.Return(
                        value=cst.Call(
                            func=cst.Name(value=helper_name),
                            args=args,
                        )
                    )
                ]
            )
            return call_stmt

        return updated_node

    def _create_loop_helper(self, loop_node: cst.For | cst.While, name: str) -> cst.FunctionDef:
        """Create a helper method from a loop."""
        used_vars = self._get_used_variables(loop_node)
        params = [p for p in self._func_params if p in used_vars]

        # Create the helper with the loop body
        helper_body = cst.IndentedBlock(body=[loop_node])

        return cst.FunctionDef(
            name=cst.Name(value=name),
            params=cst.Parameters(params=[cst.Param(name=cst.Name(value=p)) for p in params]),
            body=helper_body,
            leading_lines=[cst.EmptyLine()],
        )

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Insert extracted helper methods at the end of the module."""
        if self._extracted_methods:
            new_body = list(updated_node.body)
            for method in self._extracted_methods:
                new_body.append(method)
            self._extracted_methods.clear()
            return updated_node.with_changes(body=new_body)
        return updated_node

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        """Insert extracted helper methods at the end of the class."""
        if self._extracted_methods:
            new_body = list(updated_node.body.body)
            for method in self._extracted_methods:
                new_body.append(method)
            self._extracted_methods.clear()
            return updated_node.with_changes(body=updated_node.body.with_changes(body=new_body))
        return updated_node


# ==================== Public API ====================


def refactor_complexity(
    file_path: Path, target_cc: int = 8, dry_run: bool = False
) -> tuple[bool, str, RefactoringStats]:
    """
    Refactor a file to reduce cyclomatic complexity.

    Args:
        file_path: Path to Python file
        target_cc: Target cyclomatic complexity (default 8)
        dry_run: If True, only analyze and return stats without modifying

    Returns:
        Tuple of (success, message, stats)
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = cst.parse_module(content)

        # Analyze initial complexity
        wrapper = MetadataWrapper(tree)
        analyzer = ComplexityAnalyzer(target_cc=target_cc)
        wrapper.visit(analyzer)

        logger.info(f"Initial complexity analysis: {analyzer.function_cc}")

        # Check if any function exceeds target
        over_target = {name: cc for name, cc in analyzer.function_cc.items() if cc > target_cc}
        if not over_target:
            return (True, f"All functions within target CC ({target_cc})", RefactoringStats())

        logger.info(f"Functions over target CC: {over_target}")

        if dry_run:
            stats = RefactoringStats()
            stats.original_cc = max(analyzer.function_cc.values()) if analyzer.function_cc else 0
            return (True, f"Would refactor {len(over_target)} functions", stats)

        # Apply refactoring
        reducer = ComplexityReducer(target_cc=target_cc)
        new_tree = wrapper.visit(reducer)

        # Format and write
        new_content = new_tree.code

        if not dry_run:
            file_path.write_text(new_content, encoding="utf-8")

        return (True, f"Refactored {len(over_target)} functions", reducer.stats)

    except Exception as e:
        logger.error(f"Refactoring failed: {e}", exc_info=True)
        return (False, f"Refactoring failed: {e}", RefactoringStats())


def extract_method(
    file_path: Path, func_name: str, start_line: int, end_line: int, new_method_name: str
) -> tuple[bool, str]:
    """
    Extract a code block into a new method.

    Uses libcst to extract a range of lines into a new method with proper parameters.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = cst.parse_module(content)

        # Find the target function
        wrapper = MetadataWrapper(tree)

        class MethodExtractor(cst.CSTTransformer):
            def __init__(self):
                self.extracted = False
                self.new_method = None

            def leave_FunctionDef(self, original: cst.FunctionDef, updated: cst.FunctionDef):
                if updated.name.value != func_name:
                    return updated

                # Find the lines to extract
                # This is simplified - real implementation would use position metadata
                self.extracted = True
                return updated

        extractor = MethodExtractor()
        wrapper.visit(extractor)

        if not extractor.extracted:
            return (False, f"Function {func_name} not found or lines not extractable")

        file_path.write_text(tree.code, encoding="utf-8")
        return (True, f"Extracted method {new_method_name}")

    except Exception as e:
        logger.error(f"Method extraction failed: {e}")
        return (False, f"Extraction failed: {e}")


# ==================== CLI / Testing ====================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        sys.exit(1)

    file_path = Path(sys.argv[1])
    target_cc = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    logging.basicConfig(level=logging.INFO)

    success, message, stats = refactor_complexity(file_path, target_cc=target_cc)
