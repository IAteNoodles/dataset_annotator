from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Point:
    x: float
    y: float

    def to_list(self) -> list[float]:
        return [self.x, self.y]

    @classmethod
    def from_list(cls, lst: list[float]) -> Point:
        return cls(x=lst[0], y=lst[1])


@dataclass
class Rectangle:
    x1: float
    y1: float
    x2: float
    y2: float

    def normalize(self) -> Rectangle:
        return Rectangle(
            x1=min(self.x1, self.x2),
            y1=min(self.y1, self.y2),
            x2=max(self.x1, self.x2),
            y2=max(self.y1, self.y2),
        )

    def width(self) -> float:
        return abs(self.x2 - self.x1)

    def height(self) -> float:
        return abs(self.y2 - self.y1)

    def center(self) -> Point:
        r = self.normalize()
        return Point(x=(r.x1 + r.x2) / 2, y=(r.y1 + r.y2) / 2)

    def to_coordinates(self) -> list[list[float]]:
        r = self.normalize()
        return [[r.x1, r.y1], [r.x2, r.y2]]

    @classmethod
    def from_coordinates(cls, coords: list[list[float]]) -> Rectangle:
        return cls(x1=coords[0][0], y1=coords[0][1], x2=coords[1][0], y2=coords[1][1])

    def intersects(self, other: Rectangle) -> bool:
        r1 = self.normalize()
        r2 = other.normalize()
        return not (r1.x2 < r2.x1 or r2.x2 < r1.x1 or r1.y2 < r2.y1 or r2.y2 < r1.y1)

    def contains_point(self, point: Point) -> bool:
        r = self.normalize()
        return r.x1 <= point.x <= r.x2 and r.y1 <= point.y <= r.y2


@dataclass
class Polygon:
    points: list[Point]

    def to_coordinates(self) -> list[list[float]]:
        return [p.to_list() for p in self.points]

    @classmethod
    def from_coordinates(cls, coords: list[list[float]]) -> Polygon:
        return cls(points=[Point.from_list(p) for p in coords])

    def area(self) -> float:
        if len(self.points) < 3:
            return 0.0
        area = 0.0
        n = len(self.points)
        for i in range(n):
            j = (i + 1) % n
            area += self.points[i].x * self.points[j].y
            area -= self.points[j].x * self.points[i].y
        return abs(area) / 2.0

    def bbox(self) -> Rectangle:
        if not self.points:
            return Rectangle(0, 0, 0, 0)
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        return Rectangle(min(xs), min(ys), max(xs), max(ys))

    def contains_point(self, point: Point) -> bool:
        if len(self.points) < 3:
            return False
        inside = False
        n = len(self.points)
        for i in range(n):
            j = (i + 1) % n
            pi, pj = self.points[i], self.points[j]
            if ((pi.y > point.y) != (pj.y > point.y)) and \
               (point.x < (pj.x - pi.x) * (point.y - pi.y) / (pj.y - pi.y) + pi.x):
                inside = not inside
        return inside


def polygons_intersect(poly1: Polygon, poly2: Polygon) -> bool:
    if poly1.bbox().intersects(poly2.bbox()):
        return sat_collision(poly1.points, poly2.points)
    return False


def rect_polygon_intersect(rect: Rectangle, poly: Polygon) -> bool:
    if rect.intersects(poly.bbox()):
        rect_poly = Polygon(points=[
            Point(rect.x1, rect.y1),
            Point(rect.x2, rect.y1),
            Point(rect.x2, rect.y2),
            Point(rect.x1, rect.y2),
        ])
        return sat_collision(rect_poly.points, poly.points)
    return False


def sat_collision(poly1_points: list[Point], poly2_points: list[Point]) -> bool:
    def get_axes(points: list[Point]) -> list[Point]:
        axes = []
        n = len(points)
        for i in range(n):
            p1 = points[i]
            p2 = points[(i + 1) % n]
            edge_x = p2.x - p1.x
            edge_y = p2.y - p1.y
            length = (edge_x ** 2 + edge_y ** 2) ** 0.5
            if length > 0:
                axes.append(Point(-edge_y / length, edge_x / length))
        return axes

    def project(points: list[Point], axis: Point) -> tuple[float, float]:
        dots = [p.x * axis.x + p.y * axis.y for p in points]
        return min(dots), max(dots)

    for axis in get_axes(poly1_points) + get_axes(poly2_points):
        min1, max1 = project(poly1_points, axis)
        min2, max2 = project(poly2_points, axis)
        if max1 < min2 or max2 < min1:
            return False
    return True


def geometry_to_dict(geometry_type: str, coordinates: Any) -> dict[str, Any]:
    if geometry_type == "rectangle":
        coords = coordinates
        x1, y1 = coords[0]
        x2, y2 = coords[1]
        return {
            "type": "rect",
            "left": min(x1, x2),
            "top": min(y1, y2),
            "width": abs(x2 - x1),
            "height": abs(y2 - y1),
        }
    elif geometry_type == "polygon":
        return {
            "type": "polygon",
            "points": coordinates,
        }
    elif geometry_type == "point":
        return {
            "type": "circle",
            "left": coordinates[0],
            "top": coordinates[1],
            "radius": 5,
        }
    elif geometry_type == "line":
        return {
            "type": "line",
            "x1": coordinates[0][0],
            "y1": coordinates[0][1],
            "x2": coordinates[1][0],
            "y2": coordinates[1][1],
        }
    return {}


def dict_to_geometry(canvas_obj: dict[str, Any]) -> tuple[str, Any]:
    obj_type = canvas_obj.get("type")

    if obj_type == "rect":
        left = canvas_obj["left"]
        top = canvas_obj["top"]
        width = canvas_obj["width"]
        height = canvas_obj["height"]
        return "rectangle", [[left, top], [left + width, top + height]]
    elif obj_type == "polygon":
        return "polygon", canvas_obj["points"]
    elif obj_type == "circle":
        return "point", [canvas_obj["left"], canvas_obj["top"]]
    elif obj_type == "line":
        return "line", [[canvas_obj["x1"], canvas_obj["y1"]], [canvas_obj["x2"], canvas_obj["y2"]]]
    return "rectangle", [[0, 0], [100, 100]]