"""
Generate the NETWER globe as a single .glb model.

Rebuilds the approved HTML/Three.js prototype as real geometry so QtQuick3D
just has to load one file, instead of us reassembling the globe from engine
primitives at runtime (which kept coming out wrong).

The model contains:
  - a translucent dark core sphere
  - a blue wireframe shell (meridians + latitude rings) built from thin tori
  - a purple orbital ring
  - scattered node dots on the surface

Colours are baked into the mesh as vertex/material colours, so the loader
doesn't need to reassign materials.
"""

import math
import random

import numpy as np
import trimesh


# Prototype colours (RGBA 0-255)
C_CORE = [13, 27, 61, 140]        # #0d1b3d, translucent
C_WIRE = [77, 155, 255, 200]      # #4d9bff
C_RING = [138, 124, 255, 165]     # #8a7cff
C_DOT_BLUE = [77, 155, 255, 255]
C_DOT_GREEN = [62, 201, 138, 255]

R = 1.0                 # globe radius (model units)
WIRE_TUBE = 0.008       # wireframe line thickness
RING_TUBE = 0.008
DOT_R = 0.024
DOT_COUNT = 26


def _torus(radius, tube, transform=None, sections=64, tube_sections=8):
    m = trimesh.creation.torus(
        major_radius=radius, minor_radius=tube,
        major_sections=sections, minor_sections=tube_sections)
    if transform is not None:
        m.apply_transform(transform)
    return m


def _rot(axis, degrees):
    return trimesh.transformations.rotation_matrix(
        math.radians(degrees), axis)


def build_globe() -> trimesh.Scene:
    meshes = []

    # Core sphere (translucent)
    core = trimesh.creation.icosphere(subdivisions=3, radius=R * 0.96)
    core.visual.vertex_colors = np.tile(C_CORE, (len(core.vertices), 1))
    meshes.append(core)

    # Wireframe shell
    wire_parts = []

    # Meridians: vertical rings rotated around the Y axis
    for i in range(6):
        t = _rot([0, 1, 0], i * 30) @ _rot([1, 0, 0], 90)
        wire_parts.append(_torus(R, WIRE_TUBE, t))

    # Latitude rings: horizontal, shrinking toward the poles
    for lat in (-60, -30, 0, 30, 60):
        rad = R * math.cos(math.radians(lat))
        y = R * math.sin(math.radians(lat))
        t = trimesh.transformations.translation_matrix([0, y, 0])
        wire_parts.append(_torus(rad, WIRE_TUBE, t))

    wire = trimesh.util.concatenate(wire_parts)
    wire.visual.vertex_colors = np.tile(C_WIRE, (len(wire.vertices), 1))
    meshes.append(wire)

    # Orbital ring (purple, tilted)
    ring_t = _rot([1, 0, 0], 75)
    ring = _torus(R * 1.33, RING_TUBE, ring_t, sections=96)
    ring.visual.vertex_colors = np.tile(C_RING, (len(ring.vertices), 1))
    meshes.append(ring)

    # Surface node dots
    rng = random.Random(7)
    dot_parts = []
    dot_colors = []
    for _ in range(DOT_COUNT):
        phi = math.acos(2 * rng.random() - 1)
        theta = 2 * math.pi * rng.random()
        r = R * 1.02
        pos = [
            r * math.sin(phi) * math.cos(theta),
            r * math.cos(phi),
            r * math.sin(phi) * math.sin(theta),
        ]
        d = trimesh.creation.icosphere(subdivisions=1, radius=DOT_R)
        d.apply_translation(pos)
        color = C_DOT_GREEN if rng.random() > 0.62 else C_DOT_BLUE
        dot_parts.append(d)
        dot_colors.append(np.tile(color, (len(d.vertices), 1)))

    dots = trimesh.util.concatenate(dot_parts)
    dots.visual.vertex_colors = np.vstack(dot_colors)
    meshes.append(dots)

    return trimesh.Scene(meshes)


if __name__ == "__main__":
    import os
    scene = build_globe()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "netwer_globe.glb")
    data = scene.export(file_type="glb")
    with open(out, "wb") as f:
        f.write(data)
    print(f"Saved {out} ({len(data) / 1024:.0f} KB)")
    print(f"Meshes: {len(scene.geometry)}")
    bounds = scene.bounds
    print(f"Bounds: {bounds[0].round(2)} .. {bounds[1].round(2)}")
