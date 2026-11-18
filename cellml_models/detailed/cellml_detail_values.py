"""Resolve direct and safely inferable CellML variable values at t=0."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(text: str) -> float | None:
    try:
        value = float(text.strip())
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, AttributeError):
        return None


def _math_text(node: ET.Element) -> str:
    tag = local(node.tag)
    children = list(node)
    if tag in ("ci", "cn"):
        return " ".join("".join(node.itertext()).split())
    if tag == "apply" and children:
        operator = local(children[0].tag)
        values = [_math_text(child) for child in children[1:]]
        symbol = {"plus": "+", "minus": "−", "times": "×", "divide": "/", "power": "^"}.get(operator)
        if symbol:
            return f" {symbol} ".join(values)
        return f"{operator}({', '.join(values)})"
    return " ".join("".join(node.itertext()).split())


def _evaluate(node: ET.Element, component: str, values: dict[tuple[str, str], float]):
    tag = local(node.tag)
    children = list(node)
    if tag == "math":
        return _evaluate(children[0], component, values) if children else None
    if tag == "ci":
        name = " ".join("".join(node.itertext()).split())
        return values.get((component, name))
    if tag == "cn":
        text = "".join(node.itertext()).strip()
        if local(node.get("type", "")) == "rational" and "<sep" in ET.tostring(node, encoding="unicode"):
            parts = [part.strip() for part in text.split()]
            if len(parts) >= 2:
                numerator, denominator = _number(parts[0]), _number(parts[1])
                return numerator / denominator if numerator is not None and denominator else None
        return _number(text)
    if tag != "apply" or not children:
        return None

    operator = local(children[0].tag)
    args = [_evaluate(child, component, values) for child in children[1:]]
    if any(value is None for value in args):
        return None
    try:
        if operator == "plus":
            return sum(args)
        if operator == "times":
            result = 1.0
            for value in args:
                result *= value
            return result
        if operator == "minus" and len(args) == 1:
            return -args[0]
        if operator == "minus" and len(args) == 2:
            return args[0] - args[1]
        if operator == "divide" and len(args) == 2 and args[1] != 0:
            return args[0] / args[1]
        if operator == "power" and len(args) == 2:
            return args[0] ** args[1]
    except (ArithmeticError, OverflowError, ValueError):
        return None
    return None


def _variable_key(variable: ET.Element, component_name: str) -> tuple[str, str]:
    return component_name, variable.get("name", "")


def _equivalence_groups(root: ET.Element, variables: dict[tuple[str, str], ET.Element]):
    parent = {key: key for key in variables}

    def find(key):
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    def union(left, right):
        if left in parent and right in parent:
            parent[find(right)] = find(left)

    for connection in root.iter():
        if local(connection.tag) != "connection":
            continue
        component_pair = next((item for item in connection if local(item.tag) == "map_components"), None)
        if component_pair is None:
            continue
        component_1 = component_pair.get("component_1", "")
        component_2 = component_pair.get("component_2", "")
        for mapping in connection:
            if local(mapping.tag) != "map_variables":
                continue
            left = (component_1, mapping.get("variable_1", ""))
            right = (component_2, mapping.get("variable_2", ""))
            union(left, right)

    groups = {}
    for key in parent:
        groups.setdefault(find(key), []).append(key)
    return list(groups.values())


def _equations(root: ET.Element):
    for component in root.iter():
        if local(component.tag) != "component":
            continue
        component_name = component.get("name", "")
        for math_node in component.iter():
            if local(math_node.tag) != "apply":
                continue
            parts = list(math_node)
            if len(parts) >= 3 and local(parts[0].tag) == "eq" and local(parts[1].tag) == "ci":
                target = " ".join("".join(parts[1].itertext()).split())
                yield component_name, target, parts[2], _math_text(parts[2])


def resolve_variable_values(root: ET.Element):
    """Map variables through CellML connections and evaluate simple equations."""
    variables = {}
    for component in root.iter():
        if local(component.tag) != "component":
            continue
        component_name = component.get("name", "")
        for variable in component:
            if local(variable.tag) == "variable":
                variables[_variable_key(variable, component_name)] = variable

    values = {}
    statuses = {}
    notes = {}
    for key, variable in variables.items():
        value = _number(variable.get("initial_value", ""))
        if value is not None:
            values[key] = value
            statuses[key] = "Initial value (direct)"
            notes[key] = ""

    groups = _equivalence_groups(root, variables)
    equations = list(_equations(root))

    for _ in range(max(1, len(variables))):
        changed = False
        for group in groups:
            known = [key for key in group if key in values]
            unknown = [key for key in group if key not in values]
            if not known or not unknown:
                continue
            units = {variables[key].get("units", "") for key in known + unknown}
            known_values = [values[key] for key in known]
            consistent = all(math.isclose(known_values[0], value, rel_tol=1e-9, abs_tol=1e-12)
                             for value in known_values[1:])
            if len(units) != 1 or not consistent:
                for key in unknown:
                    notes[key] = "Connected variables have differing units or initial values; no mapped value assigned."
                continue
            source = known[0]
            for key in unknown:
                values[key] = values[source]
                statuses[key] = "Mapped"
                notes[key] = f"Mapped from {source[0]}/{source[1]} through a CellML variable connection."
                changed = True

        for component_name, variable_name, expression, expression_text in equations:
            target = (component_name, variable_name)
            if target in values or target not in variables:
                continue
            value = _evaluate(expression, component_name, values)
            if value is None or not math.isfinite(value):
                continue
            values[target] = value
            statuses[target] = "Calculated at t=0"
            notes[target] = f"Evaluated algebraic relation: {variable_name} = {expression_text}."
            changed = True
        if not changed:
            break

    resolved = {}
    for key, variable in variables.items():
        resolved[key] = {
            "value": values.get(key),
            "status": statuses.get(key, "Not verified"),
            "notes": notes.get(key, "No direct initial_value or safely resolvable t=0 value found."),
            "units": variable.get("units", ""),
            "metadata_id": variable.get("{http://www.cellml.org/metadata/1.0#}id", ""),
            "variable": variable,
        }
    return resolved
