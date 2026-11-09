"""
Fast rule-based refactoring for cyclomatic complexity reduction.
Uses simple AST-based transformations instead of full libcst parsing.
Creates self-contained helper functions with proper parameters.
"""

import ast
import sys
from pathlib import Path


class FastComplexityReducer:
    """Fast rule-based complexity reduction using simple AST transformations."""

    def __init__(self, target_cc: int = 8):
        self.target_cc = target_cc
        self.helper_counter = 0
        self.helpers: list[str] = []
        self._extracted_vars: set[str] = set()

    def calculate_cc(self, node: ast.AST) -> int:
        """Calculate cyclomatic complexity of a function."""
        cc = 1
        for node in ast.walk(node):
            if isinstance(
                node,
                (
                    ast.If,
                    ast.While,
                    ast.For,
                    ast.ExceptHandler,
                    ast.With,
                    ast.Assert,
                    ast.BoolOp,
                    ast.Compare,
                    ast.IfExp,
                ),
            ):
                cc += 1
        return cc

    def should_extract_if(self, if_stmt: ast.If) -> bool:
        """Determine if an if statement should be extracted."""
        return self._is_guard_clause(if_stmt) or self._is_complex_condition(if_stmt.test) or self._has_nested_ifs(if_stmt)

    def should_extract_try(self, try_stmt: ast.Try) -> bool:
        """Determine if a try statement should be extracted."""
        if len(try_stmt.handlers) > 1:
            return True
        if self._has_nested_try(try_stmt):
            return True
        if self._has_complex_body(try_stmt.body):
            return True
        for handler in try_stmt.handlers:
            if self._has_complex_body(handler.body):
                return True
        return True

    def _has_nested_ifs(self, if_stmt: ast.If) -> bool:
        for node in ast.walk(if_stmt):
            if node is if_stmt:
                continue
            if isinstance(node, ast.If):
                return True
        return False

    def _has_nested_try(self, try_stmt: ast.Try) -> bool:
        for node in ast.walk(try_stmt):
            if node is try_stmt:
                continue
            if isinstance(node, ast.Try):
                return True
        return False

    def _has_complex_body(self, body: list[ast.stmt]) -> bool:
        return any(isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try)) for stmt in body)

    def _is_guard_clause(self, if_stmt: ast.If) -> bool:
        """Check if if statement is a guard clause (early return/continue/break)."""
        if not if_stmt.body:
            return False
        last_stmt = if_stmt.body[-1]
        return isinstance(last_stmt, (ast.Return, ast.Continue, ast.Break, ast.Raise))

    def _is_complex_condition(self, test: ast.expr) -> bool:
        if isinstance(test, ast.BoolOp):
            return True
        if isinstance(test, ast.Compare) and len(test.ops) > 2:
            return True
        return isinstance(test, ast.IfExp)

    def _collect_used_names(self, node: ast.AST) -> set[str]:
        """Collect all variable names used in a node."""
        names = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                names.add(n.id)
        return names

    def _find_extractable_blocks(self, func_node: ast.FunctionDef) -> list[tuple]:
        blocks = []

        def visit(node):
            if isinstance(node, ast.If) and self.should_extract_if(node):
                blocks.append((node, "if"))
            elif isinstance(node, ast.Try) and self.should_extract_try(node):
                blocks.append((node, "try"))
            for child in ast.iter_child_nodes(node):
                visit(child)

        visit(func_node)
        return blocks

    def extract_complex_blocks(self, func_node: ast.FunctionDef) -> tuple:
        self.helper_counter = 0
        self.helpers = []
        blocks = self._find_extractable_blocks(func_node)
        if not blocks:
            return (func_node, [])
        transformer = BlockExtractor(self)
        new_func = transformer.visit(func_node)
        new_func = ast.fix_missing_locations(new_func)
        return (new_func, self.helpers)

    def _create_helper_from_if(self, name: str, if_stmt: ast.If, func_args: list[str]) -> str:
        """Create a helper function from an if statement with proper parameters."""
        used_names = self._collect_used_names(if_stmt)
        params = [n for n in func_args if n in used_names]
        params_str = ", ".join(params)

        if hasattr(ast, "unparse"):
            condition_code = ast.unparse(if_stmt.test)
            body_code = ast.unparse(ast.Module(body=if_stmt.body, type_ignores=[]))
            orelse_code = ast.unparse(ast.Module(body=if_stmt.orelse, type_ignores=[])) if if_stmt.orelse else ""
        else:
            condition_code = ast.dump(if_stmt.test)
            body_code = str(if_stmt.body)
            orelse_code = str(if_stmt.orelse) if if_stmt.orelse else ""

        lines = [
            f"def {name}({params_str}):",
            '    """Extracted condition helper."""',
            f"    if {condition_code}:",
        ]
        for line in body_code.splitlines():
            lines.append(f"        {line}")
        if orelse_code:
            lines.append("    else:")
            for line in orelse_code.splitlines():
                lines.append(f"        {line}")
        return "\n".join(lines)

    def _create_helper_from_try(self, name: str, try_stmt: ast.Try, func_args: list[str]) -> str:
        """Create a helper function from a try statement with proper parameters."""
        used_names = self._collect_used_names(try_stmt)
        params = [n for n in func_args if n in used_names]
        params_str = ", ".join(params)

        if hasattr(ast, "unparse"):
            body_lines = ast.unparse(ast.Module(body=try_stmt.body, type_ignores=[])).splitlines()
            handlers_code = []
            for handler in try_stmt.handlers:
                exc_type = ast.unparse(handler.type) if handler.type else "Exception"
                handler_body = ast.unparse(ast.Module(body=handler.body, type_ignores=[]))
                handlers_code.append(f"    except {exc_type}:\n{self._indent(handler_body, 8)}")
            else_lines = []
            if try_stmt.orelse:
                else_lines = ast.unparse(ast.Module(body=try_stmt.orelse, type_ignores=[])).splitlines()
            finally_lines = []
            if try_stmt.finalbody:
                finally_lines = ast.unparse(
                    ast.Module(body=try_stmt.finalbody, type_ignores=[])
                ).splitlines()
        else:
            body_lines = [str(stmt) for stmt in try_stmt.body]
            handlers_code = []
            for handler in try_stmt.handlers:
                exc_type = ast.unparse(handler.type) if handler.type else "Exception"
                handlers_code.append(f"    except {exc_type}:")
            else_lines = []
            if try_stmt.orelse:
                else_lines = [str(stmt) for stmt in try_stmt.orelse]
            finally_lines = []
            if try_stmt.finalbody:
                finally_lines = [str(stmt) for stmt in try_stmt.finalbody]

        lines = [f"def {name}({params_str}):", '    """Extracted try/except helper."""', "    try:"]
        for line in body_lines:
            lines.append(f"        {line}")
        lines.extend(handlers_code)
        if else_lines:
            lines.append("    else:")
            for line in else_lines:
                lines.append(f"        {line}")
        if finally_lines:
            lines.append("    finally:")
            for line in finally_lines:
                lines.append(f"        {line}")
        return "\n".join(lines)

    def _indent(self, code: str, spaces: int) -> str:
        indent = " " * spaces
        return "\n".join(indent + line for line in code.splitlines())


class BlockExtractor(ast.NodeTransformer):
    """AST transformer that replaces complex blocks with helper calls."""

    def __init__(self, reducer: FastComplexityReducer):
        self.reducer = reducer
        self._func_args: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._func_args = [arg.arg for arg in node.args.args]
        self._func_args += [arg.arg for arg in node.args.posonlyargs]
        self._func_args += [arg.arg for arg in node.args.kwonlyargs]
        if node.args.vararg:
            self._func_args.append(node.args.vararg.arg)
        if node.args.kwarg:
            self._func_args.append(node.args.kwarg.arg)
        return self.generic_visit(node)

    def visit_If(self, node: ast.If):
        if self.reducer.should_extract_if(node):
            self.reducer.helper_counter += 1
            helper_name = f"_check_{self.reducer.helper_counter}"
            helper_code = self.reducer._create_helper_from_if(helper_name, node, self._func_args)
            self.reducer.helpers.append(helper_code)
            new_stmt = ast.Expr(
                value=ast.Call(func=ast.Name(helper_name, ctx=ast.Load()), args=[], keywords=[])
            )
            return ast.copy_location(new_stmt, node)
        return self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        if self.reducer.should_extract_try(node):
            self.reducer.helper_counter += 1
            helper_name = f"_handle_{self.reducer.helper_counter}"
            helper_code = self.reducer._create_helper_from_try(helper_name, node, self._func_args)
            self.reducer.helpers.append(helper_code)
            new_stmt = ast.Expr(
                value=ast.Call(func=ast.Name(helper_name, ctx=ast.Load()), args=[], keywords=[])
            )
            return ast.copy_location(new_stmt, node)
        return self.generic_visit(node)


def refactor_function_fast(file_path: Path, func_name: str, target_cc: int = 8) -> tuple[bool, str]:
    """Refactor a single function to reduce cyclomatic complexity."""
    try:
        content = file_path.read_text()
        tree = ast.parse(content)
        target_func = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                target_func = node
                break
        if not target_func:
            return (False, f"Function {func_name} not found in {file_path}")
        reducer = FastComplexityReducer(target_cc=target_cc)
        new_func, helpers = reducer.extract_complex_blocks(target_func)
        if not helpers:
            return (False, "No extractable blocks found")
        new_content = ast.unparse(tree) if hasattr(ast, "unparse") else None
        if new_content is None:
            return (False, "ast.unparse not available (Python 3.9+ required)")
        file_path.write_text(new_content + "\n\n" + "\n\n".join(helpers))
        return (True, f"Extracted {len(helpers)} helper functions")
    except Exception as e:
        return (False, f"Refactoring failed: {e}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        sys.exit(1)
    file_path = Path(sys.argv[1])
    func_name = sys.argv[2]
    target_cc = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    success, msg = refactor_function_fast(Path(sys.argv[1]), sys.argv[2], target_cc)