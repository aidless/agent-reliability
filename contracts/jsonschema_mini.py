"""最小 JSON Schema 校验器（零依赖）。

为什么不用 `jsonschema` 库：agent-reliability 的平台层必须**零第三方依赖**——
这与两个被编排的仓（mcp-guard 的 `dependencies = []`、auditable-llm-eval 的
"评测管道只用标准库"）是同一条纪律。

代价是这里只实现了一小段子集：
    type / required / properties / additionalProperties / items /
    pattern / enum / const / minimum / maximum / minItems / maxItems /
    minLength / maxLength

**不实现** oneOf/anyOf/allOf/$ref/if-then-else/format 等。
需要这些时，先想清楚是不是契约写复杂了。

正确性保证：`tests/test_joint_verdict.py` 会把本实现与参照实现
`jsonschema`（如果环境里装了）跑同一批用例逐条比对。
"""
from __future__ import annotations

import re


def validate(instance, schema, path: str = "$", root: dict | None = None) -> list[str]:
    """返回错误列表；空列表 = 通过。"""
    errors: list[str] = []

    if not isinstance(schema, dict):
        return errors

    # 顶层调用时，root = 被校验的 schema 文档本身；嵌套调用沿用传入的 root。
    # 必须在这里设好：否则后面遇到 "$ref" 时 root 还是 None，会退化成拿
    # "$ref" 所在的子 schema 当文档去解析 "#/$defs/..."，结果是永远解析失败。
    if root is None:
        root = schema

    # $ref：只支持同文档内的 JSON Pointer（"#/..."），不支持跨文档/远程引用。
    if "$ref" in schema:
        target = _resolve_ref(schema["$ref"], root)
        if target is None:
            errors.append(f"{path}: 无法解析 $ref {schema['$ref']!r}")
            return errors
        return validate(instance, target, path, root)

    # type
    if "type" in schema:
        expected = schema["type"]
        if isinstance(expected, str):
            expected = [expected]
        if not any(_is_type(instance, t) for t in expected):
            errors.append(f"{path}: 期望类型 {expected}，实际 {type(instance).__name__}")
            return errors  # 类型不对时，后续约束没有意义

    # const / enum
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: 期望常量 {schema['const']!r}，实际 {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} 不在枚举 {schema['enum']} 内")

    # 数值
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")

    # 字符串
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: {instance!r} 不匹配 pattern {schema['pattern']!r}")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: 字符串长度 {len(instance)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: 字符串长度 {len(instance)} > maxLength {schema['maxLength']}")

    # 数组
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: 数组长度 {len(instance)} < minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: 数组长度 {len(instance)} > maxItems {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                errors.extend(validate(item, item_schema, f"{path}[{i}]", root))

    # 对象
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: 缺少必填字段 {key!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in instance:
                errors.extend(validate(instance[key], sub, f"{path}.{key}", root))
        additional = schema.get("additionalProperties", True)
        if additional is False:
            extra = sorted(set(instance) - set(props))
            if extra:
                errors.append(f"{path}: 出现未声明字段 {extra}")
        elif isinstance(additional, dict):
            for key in sorted(set(instance) - set(props)):
                errors.extend(validate(instance[key], additional, f"{path}.{key}", root))

    return errors


def _resolve_ref(ref: str, root: dict):
    """解析 "#/a/b/c" 形式的本地 JSON Pointer。"""
    if not ref.startswith("#/"):
        return None
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def _is_type(instance, t: str) -> bool:
    if t == "object":
        return isinstance(instance, dict)
    if t == "array":
        return isinstance(instance, list)
    if t == "string":
        return isinstance(instance, str)
    if t == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if t == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if t == "boolean":
        return isinstance(instance, bool)
    if t == "null":
        return instance is None
    return True  # 未知类型关键字不拦截（不猜）
