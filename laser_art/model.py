from dataclasses import dataclass, field
import math

Point = tuple[float, float]

@dataclass(frozen=True)
class Manufacturing:
    width: int = 6400
    height: int = 7200
    dpi: int = 600
    radius: int = 24  # Every feature is a union of identical 49-pixel disks.
    boundary: tuple[int, int, int, int] = (150, 150, 6249, 7049)
    boundary_width: int = 38

@dataclass
class Component:
    id: str
    priority: int
    paths: list[list[Point]]
    parent: str | None = None
    mirror: bool = True

@dataclass
class Master:
    subject: str
    core: Component
    components: list[Component]
    settings: Manufacturing = field(default_factory=Manufacturing)

    def removal_stages(self, layers: int) -> list[list[Component]]:
        if layers < 2:
            raise ValueError("At least two layers are required.")
        ordered = sorted(self.components, key=lambda c: (c.priority, c.id))
        if layers - 1 > len(ordered):
            raise ValueError(f"This master supports at most {len(ordered) + 1} distinct layers.")
        position = {c.id: i for i, c in enumerate(ordered)}
        if len(position) != len(ordered):
            raise ValueError("Component IDs must be unique.")
        for c in ordered:
            if c.parent and (c.parent not in position or position[c.parent] <= position[c.id]):
                raise ValueError(f"Parent of {c.id} must be removed later.")
        # Quantile stages distribute complete features across arbitrary layer counts.
        return [ordered[math.floor(i * len(ordered) / (layers - 1)):
                        math.floor((i + 1) * len(ordered) / (layers - 1))]
                for i in range(layers - 1)]


def bezier(a, b, c, d, steps=160):
    return [tuple((1-t)**3*a[j] + 3*(1-t)**2*t*b[j] +
                  3*(1-t)*t*t*c[j] + t**3*d[j] for j in (0, 1))
            for t in (i / steps for i in range(steps + 1))]


def load_master(path):
    """Restore exact saved geometry without invoking a subject renderer."""
    import json
    from pathlib import Path
    data=json.loads(Path(path).read_text())
    return Master(data['subject'], Component(**data['core']),
                  [Component(**c) for c in data['components']],
                  Manufacturing(**data['settings']))
