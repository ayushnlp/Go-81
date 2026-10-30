"""
Deterministic, Safe Mathematical Calculator for Project Go 81.
Stage 5 Deterministic Utilities:
- AST allowlist evaluator: strictly no unrestricted eval(), exec(), or shell commands
- Safe arithmetic: +, -, *, /, //, %, **, parentheses, percentages
- Division-by-zero, numerical overflow, and syntax error safety
- Query pattern recognition for calculation intents (e.g. 'what is 4*4', 'calculate 15% of 200')
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class CalculationResult:
    success: bool
    expression: str
    result: Optional[float | int] = None
    formatted: Optional[str] = None
    error: Optional[str] = None


class SafeCalculator:
    """Safe, AST-restricted mathematical expression evaluator."""

    ALLOWED_OPERATORS: Dict[type, Callable[[Any, Any], Any]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    ALLOWED_UNARY_OPERATORS: Dict[type, Callable[[Any], Any]] = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    MAX_POWER = 1000
    MAX_MAGNITUDE = 1e15

    def _eval_node(self, node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return self._eval_node(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                if abs(node.value) > self.MAX_MAGNITUDE:
                    raise OverflowError("Number exceeds maximum allowable magnitude.")
                return node.value
            raise ValueError(f"Unsupported constant type: {type(node.value)}")

        # Python < 3.8 compatibility for ast.Num
        if hasattr(ast, "Num") and isinstance(node, ast.Num):
            return node.n

        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_type = type(node.op)

            if op_type not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")

            if op_type in (ast.Div, ast.FloorDiv, ast.Mod):
                if right == 0:
                    raise ZeroDivisionError("Division by zero is mathematically undefined.")

            if op_type is ast.Pow:
                if abs(right) > self.MAX_POWER:
                    raise OverflowError(f"Exponent exceeds safe power limit ({self.MAX_POWER}).")

            op_fn = self.ALLOWED_OPERATORS[op_type]
            res = op_fn(left, right)

            if isinstance(res, (int, float)) and abs(res) > self.MAX_MAGNITUDE:
                raise OverflowError("Calculation result exceeds maximum allowable magnitude.")
            return res

        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_type = type(node.op)
            if op_type not in self.ALLOWED_UNARY_OPERATORS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            return self.ALLOWED_UNARY_OPERATORS[op_type](operand)

        raise ValueError(f"Unsupported syntax expression element: {type(node).__name__}")

    def evaluate(self, expr_str: str) -> CalculationResult:
        """
        Safely evaluates an arithmetic expression string.
        """
        raw = expr_str.strip()
        if not raw:
            return CalculationResult(success=False, expression=raw, error="Empty expression.")

        # Clean and normalize mathematical symbols
        cleaned = raw.replace("×", "*").replace("÷", "/").replace("^", "**")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Handle 'X% of Y' pattern -> '(X / 100) * Y'
        pct_of_match = re.match(r"^([\d.]+)\s*%\s*of\s*([\d.]+)$", cleaned, re.IGNORECASE)
        if pct_of_match:
            pct_val = float(pct_of_match.group(1))
            base_val = float(pct_of_match.group(2))
            res = (pct_val / 100.0) * base_val
            # Format nicely
            if res.is_integer():
                res = int(res)
            return CalculationResult(
                success=True,
                expression=f"{pct_val}% of {base_val}",
                result=res,
                formatted=f"{pct_val:g}% of {base_val:g} = {res}",
            )

        # Handle trailing percentage like '50 * 10%' -> '50 * 0.1'
        cleaned = re.sub(r"([\d.]+)\s*%", r"(\1 / 100)", cleaned)

        try:
            tree = ast.parse(cleaned, mode="eval")
            val = self._eval_node(tree)

            # Round if close to integer
            if isinstance(val, float) and val.is_integer():
                val = int(val)
            elif isinstance(val, float):
                val = round(val, 8)

            return CalculationResult(
                success=True,
                expression=raw,
                result=val,
                formatted=f"{raw} = {val}",
            )
        except ZeroDivisionError:
            return CalculationResult(
                success=False,
                expression=raw,
                error="Division by zero is mathematically undefined.",
            )
        except OverflowError as oe:
            return CalculationResult(
                success=False,
                expression=raw,
                error=f"Numerical overflow: {oe}",
            )
        except Exception as e:
            return CalculationResult(
                success=False,
                expression=raw,
                error=f"Invalid arithmetic expression: {e}",
            )


def extract_arithmetic_expression(prompt: str) -> Optional[str]:
    """
    Extracts arithmetic expression from natural language query.
    Examples:
      'what is 4*4' -> '4*4'
      'calculate 15% of 80' -> '15% of 80'
      'what is (100 - 25) / 3 ?' -> '(100 - 25) / 3'
      'compute 2^8 + 14' -> '2^8 + 14'
    """
    p = prompt.strip()
    # Strip question mark
    p = re.sub(r"\?+$", "", p).strip()

    # Prefixes to strip
    prefixes = [
        r"^what\s+is\s+the\s+result\s+of\s+",
        r"^what\s+is\s+the\s+value\s+of\s+",
        r"^what\s+is\s+",
        r"^calculate\s+",
        r"^compute\s+",
        r"^evaluate\s+",
        r"^solve\s+",
        r"^how\s+much\s+is\s+",
    ]
    candidate = p
    for pref in prefixes:
        candidate = re.sub(pref, "", candidate, flags=re.IGNORECASE).strip()

    # Check if candidate has digits and mathematical operators
    # or is 'X% of Y'
    if re.match(r"^[\d.]+\s*%\s*of\s*[\d.]+$", candidate, re.IGNORECASE):
        return candidate

    # Allowed characters in standard math expression: digits, operators, parens, dot, spaces
    if re.match(r"^[\d\s+\-*/÷×^().%]+$", candidate):
        # Must contain at least one operator and at least one digit
        has_digit = any(c.isdigit() for c in candidate)
        has_op = any(c in "+-*/÷×^%" for c in candidate)
        if has_digit and has_op:
            return candidate

    return None


def is_arithmetic_query(prompt: str) -> bool:
    """Returns True if the user prompt is a mathematical calculation query."""
    return extract_arithmetic_expression(prompt) is not None


def evaluate_math_expression(prompt: str) -> Optional[CalculationResult]:
    """Extracts and evaluates math expression from query if applicable."""
    expr = extract_arithmetic_expression(prompt)
    if not expr:
        return None
    calc = SafeCalculator()
    return calc.evaluate(expr)

