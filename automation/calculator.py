"""
calculator.py
=============
Safe arithmetic expression evaluation and unit conversion — handles the
CALCULATION intent category from brain/classifier.py.

Arithmetic uses Python's `ast` module to parse and evaluate expressions
through an explicit whitelist of allowed node types and operators,
rather than a raw `eval()`, so arbitrary code execution is not possible
even though this ultimately processes user-controlled (voice/text)
input.
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Optional, Union

from core.logger import get_logger

logger = get_logger(__name__)


class CalculationError(RuntimeError):
    """Raised when an expression can't be safely parsed/evaluated, or a
    unit conversion is unsupported."""


# --------------------------------------------------------------------------- #
# Safe arithmetic evaluator
# --------------------------------------------------------------------------- #

_ALLOWED_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_MAX_POWER_EXPONENT = 1000  # guard against pathological a**b DoS with huge exponents


def _safe_eval_node(node: ast.AST) -> Union[int, float]:
    """Recursively evaluate an AST node, only permitting numeric literals
    and the whitelisted arithmetic operators above."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise CalculationError(f"Unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BINARY_OPS:
            raise CalculationError(f"Operator '{op_type.__name__}' is not allowed.")

        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)

        if op_type is ast.Pow and (abs(right) > _MAX_POWER_EXPONENT):
            raise CalculationError("Exponent too large.")
        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise CalculationError("Division by zero.")

        return _ALLOWED_BINARY_OPS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_UNARY_OPS:
            raise CalculationError(f"Unary operator '{op_type.__name__}' is not allowed.")
        return _ALLOWED_UNARY_OPS[op_type](_safe_eval_node(node.operand))

    raise CalculationError(f"Unsupported expression element: {type(node).__name__}")


def evaluate_expression(expression: str) -> Union[int, float]:
    """
    Safely evaluate a plain arithmetic expression string, e.g.
    "2 + 3 * (4 - 1)" -> 11.

    Raises:
        CalculationError: on invalid syntax, disallowed operations
            (anything beyond +-*/%**, parentheses, and numeric
            literals), division by zero, or an oversized exponent.
    """
    cleaned = expression.strip()
    if not cleaned:
        raise CalculationError("Empty expression.")

    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as exc:
        raise CalculationError(f"Could not parse expression '{expression}': {exc}") from exc

    result = _safe_eval_node(tree)
    logger.debug("Evaluated expression '%s' = %s", expression, result)
    return result


def format_result(value: Union[int, float]) -> str:
    """Format a numeric result naturally for speech/display (avoiding
    unnecessary trailing '.0' on whole-number floats)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


# --------------------------------------------------------------------------- #
# Unit conversion
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class UnitDefinition:
    name: str
    aliases: tuple[str, ...]
    to_base_factor: float  # multiply by this to convert TO the category's base unit
    offset: float = 0.0    # for affine conversions like temperature


# Base units per category: length -> meters, mass -> kilograms,
# volume -> liters, temperature handled specially (affine, not just scale).
_LENGTH_UNITS = [
    UnitDefinition("meter", ("m", "meter", "meters", "metre", "metres"), 1.0),
    UnitDefinition("kilometer", ("km", "kilometer", "kilometers", "kilometre"), 1000.0),
    UnitDefinition("centimeter", ("cm", "centimeter", "centimeters"), 0.01),
    UnitDefinition("millimeter", ("mm", "millimeter", "millimeters"), 0.001),
    UnitDefinition("mile", ("mi", "mile", "miles"), 1609.344),
    UnitDefinition("yard", ("yd", "yard", "yards"), 0.9144),
    UnitDefinition("foot", ("ft", "foot", "feet"), 0.3048),
    UnitDefinition("inch", ("in", "inch", "inches"), 0.0254),
]

_MASS_UNITS = [
    UnitDefinition("kilogram", ("kg", "kilogram", "kilograms", "kilo", "kilos"), 1.0),
    UnitDefinition("gram", ("g", "gram", "grams"), 0.001),
    UnitDefinition("pound", ("lb", "lbs", "pound", "pounds"), 0.45359237),
    UnitDefinition("ounce", ("oz", "ounce", "ounces"), 0.028349523125),
]

_VOLUME_UNITS = [
    UnitDefinition("liter", ("l", "liter", "liters", "litre", "litres"), 1.0),
    UnitDefinition("milliliter", ("ml", "milliliter", "milliliters"), 0.001),
    UnitDefinition("gallon", ("gal", "gallon", "gallons"), 3.785411784),
    UnitDefinition("cup", ("cup", "cups"), 0.2365882365),
]

_ALL_UNIT_CATEGORIES: dict[str, list[UnitDefinition]] = {
    "length": _LENGTH_UNITS,
    "mass": _MASS_UNITS,
    "volume": _VOLUME_UNITS,
}

_TEMPERATURE_ALIASES: dict[str, tuple[str, ...]] = {
    "celsius": ("c", "celsius", "centigrade"),
    "fahrenheit": ("f", "fahrenheit"),
    "kelvin": ("k", "kelvin"),
}


def _find_unit(unit_name: str) -> Optional[tuple[str, UnitDefinition]]:
    lowered = unit_name.strip().lower()
    for category, units in _ALL_UNIT_CATEGORIES.items():
        for unit in units:
            if lowered in unit.aliases:
                return category, unit
    return None


def _resolve_temperature_alias(unit_name: str) -> Optional[str]:
    lowered = unit_name.strip().lower()
    for canonical, aliases in _TEMPERATURE_ALIASES.items():
        if lowered in aliases:
            return canonical
    return None


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """Temperature conversion is affine, not linear-scale, so it needs
    its own formula set rather than the simple factor-based approach."""
    # Normalize to Celsius first.
    if from_unit == "fahrenheit":
        celsius = (value - 32) * 5 / 9
    elif from_unit == "kelvin":
        celsius = value - 273.15
    else:
        celsius = value

    if to_unit == "fahrenheit":
        return celsius * 9 / 5 + 32
    elif to_unit == "kelvin":
        return celsius + 273.15
    return celsius


def convert_units(value: float, from_unit: str, to_unit: str) -> float:
    """
    Convert `value` from `from_unit` to `to_unit`. Supports length,
    mass, volume (linear scale conversions), and temperature (affine
    conversion), each auto-detected from the unit names given.

    Raises:
        CalculationError: if either unit is unrecognized, or the two
            units belong to different (incompatible) categories.
    """
    temp_from = _resolve_temperature_alias(from_unit)
    temp_to = _resolve_temperature_alias(to_unit)
    if temp_from and temp_to:
        result = _convert_temperature(value, temp_from, temp_to)
        logger.debug("Converted %s %s -> %s %s", value, from_unit, result, to_unit)
        return result
    if temp_from or temp_to:
        raise CalculationError(f"Cannot convert between '{from_unit}' and '{to_unit}' (incompatible units).")

    from_match = _find_unit(from_unit)
    to_match = _find_unit(to_unit)

    if from_match is None:
        raise CalculationError(f"Unrecognized unit: '{from_unit}'.")
    if to_match is None:
        raise CalculationError(f"Unrecognized unit: '{to_unit}'.")

    from_category, from_def = from_match
    to_category, to_def = to_match

    if from_category != to_category:
        raise CalculationError(
            f"Cannot convert between '{from_unit}' ({from_category}) and "
            f"'{to_unit}' ({to_category}) — different unit categories."
        )

    base_value = value * from_def.to_base_factor
    result = base_value / to_def.to_base_factor
    logger.debug("Converted %s %s -> %s %s", value, from_unit, result, to_unit)
    return result
    