"""
automation/calculator.py
========================

Safe arithmetic expression evaluation and unit conversion for AssistantX.

Features:
    - Safe arithmetic evaluation using Python AST
    - No raw eval()
    - Explicit operator whitelist
    - Expression length/depth protection
    - Large-number protection
    - Division/modulo-by-zero protection
    - NaN/Infinity protection
    - Unit conversion
    - Length, mass, volume, area, time and temperature
    - Human-friendly result formatting
    - Structured calculation results
    - Safe wrappers
    - Diagnostics

Designed to handle CALCULATION intent requests from:
    brain/classifier.py

Examples:
    evaluate_expression("2 + 3 * 4")
    evaluate_expression("(100 - 25) / 5")
    convert_units(10, "km", "m")
    convert_units(100, "celsius", "fahrenheit")
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Union

from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Types
# ============================================================================

Number = Union[int, float]


# ============================================================================
# Constants
# ============================================================================

MAX_EXPRESSION_LENGTH = 1_000
MAX_AST_DEPTH = 50
MAX_POWER_EXPONENT = 1_000
MAX_ABSOLUTE_RESULT = 10**100

DEFAULT_FLOAT_PRECISION = 10


# ============================================================================
# Exceptions
# ============================================================================


class CalculationError(RuntimeError):
    """Base exception for calculation and conversion failures."""


class ExpressionValidationError(CalculationError):
    """Raised when an arithmetic expression is invalid or unsafe."""


class ArithmeticError(CalculationError):
    """Raised when arithmetic cannot be completed safely."""


class UnitConversionError(CalculationError):
    """Raised when a unit conversion is invalid or unsupported."""


class UnsupportedUnitError(UnitConversionError):
    """Raised when a unit is not recognized."""


class IncompatibleUnitError(UnitConversionError):
    """Raised when two units belong to different categories."""


# ============================================================================
# Result Models
# ============================================================================


@dataclass(frozen=True)
class CalculationResult:
    """Structured result for arithmetic calculations."""

    expression: str
    value: Number
    formatted: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "expression": self.expression,
            "value": self.value,
            "formatted": self.formatted,
        }


@dataclass(frozen=True)
class ConversionResult:
    """Structured result for unit conversions."""

    value: float
    from_unit: str
    to_unit: str
    result: float
    formatted: str
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "from_unit": self.from_unit,
            "to_unit": self.to_unit,
            "result": self.result,
            "formatted": self.formatted,
            "category": self.category,
        }


# ============================================================================
# Safe Arithmetic Operators
# ============================================================================


_ALLOWED_BINARY_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


_ALLOWED_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


# ============================================================================
# AST Helpers
# ============================================================================


def _validate_expression_input(expression: str) -> str:
    """Validate and normalize an arithmetic expression."""
    if expression is None:
        raise ExpressionValidationError(
            "Expression cannot be None."
        )

    if not isinstance(expression, str):
        raise ExpressionValidationError(
            "Expression must be a string."
        )

    cleaned = expression.strip()

    if not cleaned:
        raise ExpressionValidationError(
            "Expression cannot be empty."
        )

    if len(cleaned) > MAX_EXPRESSION_LENGTH:
        raise ExpressionValidationError(
            f"Expression is too long. Maximum length is "
            f"{MAX_EXPRESSION_LENGTH} characters."
        )

    return cleaned


def _ast_depth(node: ast.AST, current_depth: int = 0) -> int:
    """Calculate AST depth."""
    if current_depth > MAX_AST_DEPTH:
        return current_depth

    children = list(ast.iter_child_nodes(node))

    if not children:
        return current_depth

    return max(
        _ast_depth(child, current_depth + 1)
        for child in children
    )


def _validate_ast(tree: ast.AST) -> None:
    """Validate AST depth and allowed structure."""
    depth = _ast_depth(tree)

    if depth > MAX_AST_DEPTH:
        raise ExpressionValidationError(
            f"Expression is too complex. Maximum AST depth is "
            f"{MAX_AST_DEPTH}."
        )


def _validate_numeric(value: Number) -> Number:
    """Ensure a calculation result is a finite, reasonable number."""
    if isinstance(value, bool):
        raise ArithmeticError(
            "Boolean values are not valid numeric operands."
        )

    if not isinstance(value, (int, float)):
        raise ArithmeticError(
            f"Unsupported numeric type: {type(value).__name__}."
        )

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ArithmeticError(
                "Calculation produced a non-finite result."
            )

    try:
        if abs(value) > MAX_ABSOLUTE_RESULT:
            raise ArithmeticError(
                "Calculation result is too large."
            )
    except OverflowError as exc:
        raise ArithmeticError(
            "Calculation result is too large."
        ) from exc

    return value


# ============================================================================
# Safe AST Evaluation
# ============================================================================


def _safe_eval_node(
    node: ast.AST,
    *,
    depth: int = 0,
) -> Number:
    """
    Recursively evaluate an AST node using an explicit whitelist.

    Allowed:
        - Integer literals
        - Float literals
        - +, -, *, /, //, %, **
        - Unary + and -
        - Parentheses
    """
    if depth > MAX_AST_DEPTH:
        raise ExpressionValidationError(
            "Expression nesting is too deep."
        )

    # ------------------------------------------------------------------
    # Expression root
    # ------------------------------------------------------------------

    if isinstance(node, ast.Expression):
        return _safe_eval_node(
            node.body,
            depth=depth + 1,
        )

    # ------------------------------------------------------------------
    # Numeric constants
    # ------------------------------------------------------------------

    if isinstance(node, ast.Constant):
        value = node.value

        # bool is a subclass of int, so explicitly reject it.
        if isinstance(value, bool):
            raise ExpressionValidationError(
                "Boolean constants are not allowed."
            )

        if isinstance(value, (int, float)):
            return _validate_numeric(value)

        raise ExpressionValidationError(
            f"Unsupported constant type: "
            f"{type(value).__name__}."
        )

    # ------------------------------------------------------------------
    # Binary operations
    # ------------------------------------------------------------------

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)

        if op_type not in _ALLOWED_BINARY_OPS:
            raise ExpressionValidationError(
                f"Operator '{op_type.__name__}' is not allowed."
            )

        left = _safe_eval_node(
            node.left,
            depth=depth + 1,
        )

        right = _safe_eval_node(
            node.right,
            depth=depth + 1,
        )

        # Division / modulo by zero.
        if op_type in (
            ast.Div,
            ast.FloorDiv,
            ast.Mod,
        ):
            if right == 0:
                raise ArithmeticError(
                    "Division by zero is not allowed."
                )

        # Protect exponentiation.
        if op_type is ast.Pow:
            if not isinstance(right, (int, float)):
                raise ArithmeticError(
                    "Exponent must be numeric."
                )

            if abs(right) > MAX_POWER_EXPONENT:
                raise ArithmeticError(
                    f"Exponent is too large. Maximum absolute "
                    f"exponent is {MAX_POWER_EXPONENT}."
                )

            # Prevent massive intermediate calculations.
            if abs(left) > 1 and right > MAX_POWER_EXPONENT:
                raise ArithmeticError(
                    "Exponentiation would produce an unsafe result."
                )

        operation = _ALLOWED_BINARY_OPS[op_type]

        try:
            result = operation(left, right)
        except ZeroDivisionError as exc:
            raise ArithmeticError(
                "Division by zero is not allowed."
            ) from exc
        except OverflowError as exc:
            raise ArithmeticError(
                "Calculation overflowed."
            ) from exc
        except ValueError as exc:
            raise ArithmeticError(
                f"Invalid arithmetic operation: {exc}"
            ) from exc

        return _validate_numeric(result)

    # ------------------------------------------------------------------
    # Unary operations
    # ------------------------------------------------------------------

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)

        if op_type not in _ALLOWED_UNARY_OPS:
            raise ExpressionValidationError(
                f"Unary operator '{op_type.__name__}' "
                f"is not allowed."
            )

        operand = _safe_eval_node(
            node.operand,
            depth=depth + 1,
        )

        try:
            result = _ALLOWED_UNARY_OPS[op_type](operand)
        except (OverflowError, ValueError) as exc:
            raise ArithmeticError(
                f"Invalid unary operation: {exc}"
            ) from exc

        return _validate_numeric(result)

    # ------------------------------------------------------------------
    # Everything else is forbidden.
    # ------------------------------------------------------------------

    raise ExpressionValidationError(
        f"Unsupported expression element: "
        f"{type(node).__name__}."
    )


# ============================================================================
# Public Arithmetic API
# ============================================================================


def evaluate_expression(expression: str) -> Number:
    """
    Safely evaluate an arithmetic expression.

    Examples:
        "2 + 3 * 4"       -> 14
        "(10 - 2) / 4"    -> 2
        "2 ** 8"          -> 256

    No arbitrary Python code can be executed.
    """
    cleaned = _validate_expression_input(expression)

    try:
        tree = ast.parse(
            cleaned,
            mode="eval",
        )
    except SyntaxError as exc:
        raise ExpressionValidationError(
            f"Invalid expression '{expression}': {exc.msg}"
        ) from exc

    _validate_ast(tree)

    result = _safe_eval_node(tree)

    result = _validate_numeric(result)

    logger.debug(
        "Evaluated expression '%s' = %s",
        cleaned,
        result,
    )

    return result


def calculate(expression: str) -> CalculationResult:
    """
    Evaluate an expression and return a structured result.
    """
    value = evaluate_expression(expression)

    return CalculationResult(
        expression=expression.strip(),
        value=value,
        formatted=format_result(value),
    )


# ============================================================================
# Result Formatting
# ============================================================================


def format_result(
    value: Number,
    *,
    precision: int = DEFAULT_FLOAT_PRECISION,
) -> str:
    """
    Format a numeric result naturally.

    Examples:
        10.0      -> "10"
        3.1415926 -> "3.1415926"
    """
    if not isinstance(value, (int, float)):
        raise CalculationError(
            "format_result expects a numeric value."
        )

    if isinstance(precision, bool) or not isinstance(
        precision,
        int,
    ):
        raise CalculationError(
            "precision must be an integer."
        )

    if precision <= 0:
        raise CalculationError(
            "precision must be greater than zero."
        )

    if isinstance(value, float):
        if not math.isfinite(value):
            raise CalculationError(
                "Cannot format a non-finite number."
            )

        if value.is_integer():
            return str(int(value))

        return f"{value:.{precision}g}"

    return str(value)


# ============================================================================
# Unit Definitions
# ============================================================================


@dataclass(frozen=True)
class UnitDefinition:
    """Definition of a linear conversion unit."""

    name: str
    aliases: tuple[str, ...]
    to_base_factor: float


# ============================================================================
# Length
# Base: meter
# ============================================================================


_LENGTH_UNITS = (
    UnitDefinition(
        "meter",
        ("m", "meter", "meters", "metre", "metres"),
        1.0,
    ),
    UnitDefinition(
        "kilometer",
        ("km", "kilometer", "kilometers", "kilometre", "kilometres"),
        1_000.0,
    ),
    UnitDefinition(
        "centimeter",
        ("cm", "centimeter", "centimeters", "centimetre", "centimetres"),
        0.01,
    ),
    UnitDefinition(
        "millimeter",
        ("mm", "millimeter", "millimeters", "millimetre", "millimetres"),
        0.001,
    ),
    UnitDefinition(
        "micrometer",
        ("um", "µm", "micrometer", "micrometers"),
        0.000001,
    ),
    UnitDefinition(
        "mile",
        ("mi", "mile", "miles"),
        1_609.344,
    ),
    UnitDefinition(
        "yard",
        ("yd", "yard", "yards"),
        0.9144,
    ),
    UnitDefinition(
        "foot",
        ("ft", "foot", "feet"),
        0.3048,
    ),
    UnitDefinition(
        "inch",
        ("in", "inch", "inches"),
        0.0254,
    ),
)


# ============================================================================
# Mass
# Base: kilogram
# ============================================================================


_MASS_UNITS = (
    UnitDefinition(
        "kilogram",
        ("kg", "kilogram", "kilograms", "kilo", "kilos"),
        1.0,
    ),
    UnitDefinition(
        "gram",
        ("g", "gram", "grams"),
        0.001,
    ),
    UnitDefinition(
        "milligram",
        ("mg", "milligram", "milligrams"),
        0.000001,
    ),
    UnitDefinition(
        "metric_ton",
        ("t", "tonne", "tonnes", "metric ton", "metric tons"),
        1_000.0,
    ),
    UnitDefinition(
        "pound",
        ("lb", "lbs", "pound", "pounds"),
        0.45359237,
    ),
    UnitDefinition(
        "ounce",
        ("oz", "ounce", "ounces"),
        0.028349523125,
    ),
)


# ============================================================================
# Volume
# Base: liter
# ============================================================================


_VOLUME_UNITS = (
    UnitDefinition(
        "liter",
        ("l", "liter", "liters", "litre", "litres"),
        1.0,
    ),
    UnitDefinition(
        "milliliter",
        ("ml", "milliliter", "milliliters", "millilitre", "millilitres"),
        0.001,
    ),
    UnitDefinition(
        "cubic_meter",
        ("m3", "m^3", "cubic meter", "cubic meters"),
        1_000.0,
    ),
    UnitDefinition(
        "gallon",
        ("gal", "gallon", "gallons"),
        3.785411784,
    ),
    UnitDefinition(
        "quart",
        ("qt", "quart", "quarts"),
        0.946352946,
    ),
    UnitDefinition(
        "pint",
        ("pt", "pint", "pints"),
        0.473176473,
    ),
    UnitDefinition(
        "cup",
        ("cup", "cups"),
        0.2365882365,
    ),
)


# ============================================================================
# Area
# Base: square meter
# ============================================================================


_AREA_UNITS = (
    UnitDefinition(
        "square_meter",
        ("m2", "m^2", "square meter", "square meters"),
        1.0,
    ),
    UnitDefinition(
        "square_kilometer",
        ("km2", "km^2", "square kilometer", "square kilometers"),
        1_000_000.0,
    ),
    UnitDefinition(
        "square_centimeter",
        ("cm2", "cm^2", "square centimeter", "square centimeters"),
        0.0001,
    ),
    UnitDefinition(
        "square_foot",
        ("ft2", "ft^2", "square foot", "square feet"),
        0.09290304,
    ),
    UnitDefinition(
        "square_yard",
        ("yd2", "yd^2", "square yard", "square yards"),
        0.83612736,
    ),
    UnitDefinition(
        "acre",
        ("acre", "acres"),
        4046.8564224,
    ),
    UnitDefinition(
        "hectare",
        ("ha", "hectare", "hectares"),
        10_000.0,
    ),
)


# ============================================================================
# Time
# Base: second
# ============================================================================


_TIME_UNITS = (
    UnitDefinition(
        "second",
        ("s", "sec", "second", "seconds"),
        1.0,
    ),
    UnitDefinition(
        "millisecond",
        ("ms", "millisecond", "milliseconds"),
        0.001,
    ),
    UnitDefinition(
        "minute",
        ("min", "minute", "minutes"),
        60.0,
    ),
    UnitDefinition(
        "hour",
        ("h", "hr", "hour", "hours"),
        3_600.0,
    ),
    UnitDefinition(
        "day",
        ("d", "day", "days"),
        86_400.0,
    ),
    UnitDefinition(
        "week",
        ("week", "weeks"),
        604_800.0,
    ),
)


# ============================================================================
# Categories
# ============================================================================


_ALL_UNIT_CATEGORIES: dict[str, tuple[UnitDefinition, ...]] = {
    "length": _LENGTH_UNITS,
    "mass": _MASS_UNITS,
    "volume": _VOLUME_UNITS,
    "area": _AREA_UNITS,
    "time": _TIME_UNITS,
}


# ============================================================================
# Temperature
# ============================================================================


_TEMPERATURE_ALIASES: dict[str, tuple[str, ...]] = {
    "celsius": (
        "c",
        "celsius",
        "centigrade",
        "°c",
    ),
    "fahrenheit": (
        "f",
        "fahrenheit",
        "°f",
    ),
    "kelvin": (
        "k",
        "kelvin",
        "°k",
    ),
}


# ============================================================================
# Unit Helpers
# ============================================================================


def _normalize_unit_name(unit_name: str) -> str:
    """Normalize a unit string."""
    if unit_name is None:
        raise UnitConversionError(
            "Unit name cannot be None."
        )

    if not isinstance(unit_name, str):
        raise UnitConversionError(
            "Unit name must be a string."
        )

    normalized = (
        unit_name
        .strip()
        .lower()
    )

    if not normalized:
        raise UnitConversionError(
            "Unit name cannot be empty."
        )

    return normalized


def _find_unit(
    unit_name: str,
) -> tuple[str, UnitDefinition] | None:
    """Find a linear unit and its category."""
    lowered = _normalize_unit_name(unit_name)

    for category, units in _ALL_UNIT_CATEGORIES.items():
        for unit in units:
            if lowered in unit.aliases:
                return category, unit

    return None


def _resolve_temperature_alias(
    unit_name: str,
) -> str | None:
    """Resolve a temperature alias to its canonical name."""
    lowered = _normalize_unit_name(unit_name)

    for canonical, aliases in _TEMPERATURE_ALIASES.items():
        if lowered in aliases:
            return canonical

    return None


def list_units() -> dict[str, list[str]]:
    """
    Return supported units grouped by category.
    """
    result: dict[str, list[str]] = {}

    for category, units in _ALL_UNIT_CATEGORIES.items():
        result[category] = [
            unit.name
            for unit in units
        ]

    result["temperature"] = list(
        _TEMPERATURE_ALIASES.keys()
    )

    return result


# ============================================================================
# Temperature Conversion
# ============================================================================


def _validate_temperature(
    value: float,
    unit: str,
) -> float:
    """Validate physical temperature where appropriate."""
    if unit == "kelvin" and value < 0:
        raise UnitConversionError(
            "Kelvin temperature cannot be below 0 K."
        )

    return value


def _convert_temperature(
    value: float,
    from_unit: str,
    to_unit: str,
) -> float:
    """
    Convert temperature through Celsius.

    Supported:
        Celsius
        Fahrenheit
        Kelvin
    """
    value = float(value)

    _validate_temperature(
        value,
        from_unit,
    )

    # Convert to Celsius.
    if from_unit == "fahrenheit":
        celsius = (value - 32.0) * 5.0 / 9.0

    elif from_unit == "kelvin":
        celsius = value - 273.15

    else:
        celsius = value

    # Convert Celsius to destination.
    if to_unit == "fahrenheit":
        result = celsius * 9.0 / 5.0 + 32.0

    elif to_unit == "kelvin":
        result = celsius + 273.15

    else:
        result = celsius

    return _validate_numeric(result)


# ============================================================================
# Unit Conversion
# ============================================================================


def convert_units(
    value: float,
    from_unit: str,
    to_unit: str,
) -> float:
    """
    Convert a numeric value between compatible units.

    Supported categories:
        - length
        - mass
        - volume
        - area
        - time
        - temperature
    """
    if isinstance(value, bool):
        raise UnitConversionError(
            "Boolean values cannot be converted."
        )

    if not isinstance(value, (int, float)):
        raise UnitConversionError(
            "Conversion value must be numeric."
        )

    value = _validate_numeric(value)

    temp_from = _resolve_temperature_alias(from_unit)
    temp_to = _resolve_temperature_alias(to_unit)

    # Temperature conversion.
    if temp_from and temp_to:
        result = _convert_temperature(
            float(value),
            temp_from,
            temp_to,
        )

        logger.debug(
            "Converted %s %s -> %s %s",
            value,
            from_unit,
            result,
            to_unit,
        )

        return result

    # One temperature + one non-temperature = incompatible.
    if temp_from or temp_to:
        raise IncompatibleUnitError(
            f"Cannot convert '{from_unit}' to '{to_unit}': "
            "different unit categories."
        )

    from_match = _find_unit(from_unit)
    to_match = _find_unit(to_unit)

    if from_match is None:
        raise UnsupportedUnitError(
            f"Unrecognized unit: '{from_unit}'."
        )

    if to_match is None:
        raise UnsupportedUnitError(
            f"Unrecognized unit: '{to_unit}'."
        )

    from_category, from_def = from_match
    to_category, to_def = to_match

    if from_category != to_category:
        raise IncompatibleUnitError(
            f"Cannot convert '{from_unit}' "
            f"({from_category}) to "
            f"'{to_unit}' ({to_category})."
        )

    try:
        base_value = (
            float(value)
            * from_def.to_base_factor
        )

        result = (
            base_value
            / to_def.to_base_factor
        )

    except (OverflowError, ZeroDivisionError) as exc:
        raise UnitConversionError(
            f"Could not convert {value} {from_unit} "
            f"to {to_unit}."
        ) from exc

    result = _validate_numeric(result)

    logger.debug(
        "Converted %s %s -> %s %s",
        value,
        from_unit,
        result,
        to_unit,
    )

    return result


def convert(
    value: float,
    from_unit: str,
    to_unit: str,
) -> ConversionResult:
    """
    Convert units and return a structured ConversionResult.
    """
    result = convert_units(
        value,
        from_unit,
        to_unit,
    )

    match = _find_unit(from_unit)

    if match:
        category = match[0]
    else:
        category = "temperature"

    return ConversionResult(
        value=float(value),
        from_unit=from_unit,
        to_unit=to_unit,
        result=result,
        formatted=format_result(result),
        category=category,
    )


# ============================================================================
# Safe Wrappers
# ============================================================================


def safe_evaluate_expression(
    expression: str,
) -> Number | None:
    """
    Safely evaluate an expression without propagating CalculationError.
    """
    try:
        return evaluate_expression(expression)

    except CalculationError as exc:
        logger.warning(
            "safe_evaluate_expression failed: %s",
            exc,
        )
        return None


def safe_calculate(
    expression: str,
) -> CalculationResult | None:
    """Safe structured calculation wrapper."""
    try:
        return calculate(expression)

    except CalculationError as exc:
        logger.warning(
            "safe_calculate failed: %s",
            exc,
        )
        return None


def safe_convert_units(
    value: float,
    from_unit: str,
    to_unit: str,
) -> float | None:
    """
    Safely convert units without propagating CalculationError.
    """
    try:
        return convert_units(
            value,
            from_unit,
            to_unit,
        )

    except CalculationError as exc:
        logger.warning(
            "safe_convert_units failed: %s",
            exc,
        )
        return None


def safe_convert(
    value: float,
    from_unit: str,
    to_unit: str,
) -> ConversionResult | None:
    """Safe structured conversion wrapper."""
    try:
        return convert(
            value,
            from_unit,
            to_unit,
        )

    except CalculationError as exc:
        logger.warning(
            "safe_convert failed: %s",
            exc,
        )
        return None


# ============================================================================
# Diagnostics
# ============================================================================


def diagnostics() -> dict[str, Any]:
    """
    Return calculator subsystem diagnostics.
    """
    units = list_units()

    return {
        "module": "automation.calculator",
        "safe_ast_evaluation": True,
        "raw_eval_used": False,
        "max_expression_length": MAX_EXPRESSION_LENGTH,
        "max_ast_depth": MAX_AST_DEPTH,
        "max_power_exponent": MAX_POWER_EXPONENT,
        "max_absolute_result": MAX_ABSOLUTE_RESULT,
        "unit_categories": list(units.keys()),
        "supported_units": units,
    }


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Types
    "Number",

    # Exceptions
    "CalculationError",
    "ExpressionValidationError",
    "ArithmeticError",
    "UnitConversionError",
    "UnsupportedUnitError",
    "IncompatibleUnitError",

    # Result models
    "CalculationResult",
    "ConversionResult",
    "UnitDefinition",

    # Constants
    "MAX_EXPRESSION_LENGTH",
    "MAX_AST_DEPTH",
    "MAX_POWER_EXPONENT",
    "MAX_ABSOLUTE_RESULT",
    "DEFAULT_FLOAT_PRECISION",

    # Arithmetic
    "evaluate_expression",
    "calculate",
    "format_result",

    # Units
    "convert_units",
    "convert",
    "list_units",

    # Safe wrappers
    "safe_evaluate_expression",
    "safe_calculate",
    "safe_convert_units",
    "safe_convert",

    # Diagnostics
    "diagnostics",
]
