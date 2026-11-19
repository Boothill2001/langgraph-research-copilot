"""Bounded AST arithmetic; no Python eval or unbounded exponentiation."""
import ast
import math
import operator

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def calculate(expression):
    if not isinstance(expression, str) or len(expression) > 200:
        raise ValueError("Expression must be at most 200 characters")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 60:
        raise ValueError("Expression too complex")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in OPS:
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and (abs(b) > 12 or abs(a) > 1e6):
                raise ValueError("Exponent bound exceeded")
            value = OPS[type(node.op)](a, b)
        else:
            raise ValueError("Only bounded numeric arithmetic is allowed")
        if isinstance(value, complex) or not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError("Result outside finite numeric bounds")
        return float(value)
    return {"expression": expression, "value": visit(tree)}
