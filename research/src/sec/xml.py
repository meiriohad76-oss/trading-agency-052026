from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable


def parse_xml(value: str) -> ET.Element:
    return ET.fromstring(value)


def elements(root: ET.Element, name: str) -> Iterable[ET.Element]:
    return (element for element in root.iter() if local_name(element.tag) == name)


def first_text(root: ET.Element, path: tuple[str, ...]) -> str | None:
    current = root
    for name in path:
        child = next((item for item in current if local_name(item.tag) == name), None)
        if child is None:
            return None
        current = child
    if current.text is None:
        return None
    text = current.text.strip()
    return text or None


def local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]
