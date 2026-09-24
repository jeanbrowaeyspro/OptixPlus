"""Lecture de référence par PyYAML, pour vérifier ``common.optix.tree.read_nodes`` nœud par nœud."""

from __future__ import annotations

import yaml

from optixplus.common.optix.tree import FIELDS, RawNode

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def pyyaml_nodes(text: str) -> list[RawNode] | None:
    """Mêmes enregistrements que ``read_nodes``, obtenus par PyYAML ; None si la racine n'est pas une mappe."""
    loader = Loader(text)
    try:
        root = loader.get_single_node()
        if not isinstance(root, yaml.MappingNode):
            return None
        records: list[RawNode] = []
        stack = [(root, -1)]
        while stack:
            ynode, parent = stack.pop()
            items = {k.value: v for k, v in ynode.value}
            record = RawNode(parent=parent, line=ynode.start_mark.line + 1, end_line=ynode.end_mark.line + 1)
            for key in FIELDS:
                if key not in items:
                    continue
                value = items[key]
                if key == "Value":
                    record.has_value = True
                    record.value_line = value.start_mark.line + 1
                    if isinstance(value, yaml.ScalarNode):
                        try:
                            record.value = loader.construct_object(value, deep=True)
                        except Exception:
                            record.value = value.value
                    continue
                setattr(record, {"Class": "klass", "File": "file"}.get(key, key.lower()), value.value)
            index = len(records)
            records.append(record)
            children = items.get("Children")
            if isinstance(children, yaml.SequenceNode):
                for child in reversed(children.value):
                    if isinstance(child, yaml.MappingNode):
                        stack.append((child, index))
        return records
    finally:
        loader.dispose()
