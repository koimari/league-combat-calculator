import bpy
import math
import os
from mathutils import Vector

ROOT = os.path.dirname(__file__)
ASSETS = os.path.join(ROOT, "assets")
OUT = os.path.join(ASSETS, "rift-native-bg-4k.png")
BLEND = os.path.join(ASSETS, "rift-native-bg-4k.blend")

# This scene is deliberately geometry-first.  No raster plate is loaded or
# enlarged: the final image is rendered directly at 3840x2160 by Blender.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for collection in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    for datablock in list(collection):
        if datablock.users == 0:
            collection.remove(datablock)


def mat(name, color, rough=0.8, metallic=0.0, emission=None, strength=0.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = rough
    shader.inputs["Metallic"].default_value = metallic
    if emission:
        shader.inputs["Emission Color"].default_value = (*emission, 1)
        shader.inputs["Emission Strength"].default_value = strength
    material.diffuse_color = (*color, 1)
    return material


def put(obj, material):
    obj.data.materials.append(material)
    return obj


def bevel(obj, width=0.1, segments=2):
    modifier = obj.modifiers.new("soft carved edge", "BEVEL")
    modifier.width = width
    modifier.segments = segments
    return obj


def cube(name, location, scale, material, rotation=0.0, edge=0.0):
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=(0, 0, rotation))
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if edge:
        bevel(obj, edge, 3)
    return put(obj, material)


def cylinder(name, location, radius, depth, material, vertices=16, rotation=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    if rotation:
        obj.rotation_euler = rotation
    bevel(obj, min(radius * 0.12, 0.09), 2)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return put(obj, material)


def sphere(name, location, radius, material, scale=(1, 1, 1), ico=False):
    if ico:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=location)
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=14, radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return put(obj, material)


def tube(name, points, radius, material, resolution=4):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.resolution_u = resolution
    data.bevel_depth = radius
    data.bevel_resolution = 4
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, coordinate in zip(spline.bezier_points, points):
        point.co = coordinate
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    return put(obj, material)


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def light(name, location, color, energy, size=2.0):
    bpy.ops.object.light_add(type="AREA", location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.energy = energy
    obj.data.color = color
    obj.data.shape = "DISK"
    obj.data.size = size
    look_at(obj, (0, 0, 0))
    return obj


void = mat("deep navy void", (0.004, 0.009, 0.015), rough=1)
basalt = mat("blue basalt", (0.018, 0.035, 0.055), rough=0.74, metallic=0.1)
earth = mat("forest earth", (0.045, 0.12, 0.09), rough=0.98)
grass = mat("emerald grass", (0.075, 0.28, 0.14), rough=0.9)
grass2 = mat("sunlit grass", (0.18, 0.46, 0.20), rough=0.86)
stone = mat("pale carved stone", (0.22, 0.30, 0.32), rough=0.74)
lane = mat("lane slate", (0.31, 0.38, 0.40), rough=0.68)
lane_line = mat("lane inlay", (0.52, 0.76, 0.70), rough=0.42, metallic=0.12, emission=(0.08, 0.30, 0.28), strength=0.3)
river = mat("turquoise river", (0.01, 0.36, 0.58), rough=0.14, metallic=0.25, emission=(0.01, 0.28, 0.52), strength=1.1)
river_glint = mat("river glint", (0.16, 0.82, 0.86), rough=0.08, metallic=0.3, emission=(0.06, 0.60, 0.72), strength=1.4)
cobalt = mat("cobalt team light", (0.025, 0.14, 0.62), rough=0.32, metallic=0.18, emission=(0.02, 0.18, 0.95), strength=2.5)
violet = mat("violet team light", (0.25, 0.04, 0.55), rough=0.32, metallic=0.18, emission=(0.5, 0.03, 0.95), strength=2.3)
gold = mat("objective gold", (0.68, 0.38, 0.08), rough=0.30, metallic=0.5, emission=(0.45, 0.16, 0.02), strength=0.8)
crystal = mat("objective aqua", (0.04, 0.55, 0.62), rough=0.12, metallic=0.18, emission=(0.02, 0.75, 0.85), strength=3.0)

# A deep, bevelled plinth gives the native render a quiet edge if the page is
# scrolled or the background is viewed without the UI veil.
cube("outer plinth", (0, 0, -1.25), (15.0, 10.0, 0.85), basalt, edge=0.42)
cube("map slab", (0, 0, -0.32), (14.35, 9.35, 0.28), earth, edge=0.34)
cube("central terrain", (0, 0, 0.05), (13.9, 8.9, 0.22), grass, edge=0.32)

# Banks and terraces break up the plane without using a raster texture.
for x, y, sx, sy, z in [(-9.8, 5.4, 3.0, 1.4, 0.46), (8.9, 5.2, 3.5, 1.3, 0.42), (-9.8, -5.1, 3.0, 1.4, 0.5), (9.0, -5.0, 3.2, 1.4, 0.44), (-3.0, 5.2, 1.7, 1.0, 0.35), (3.0, -5.0, 1.8, 1.1, 0.36)]:
    cube("raised jungle terrace", (x, y, z), (sx, sy, z), grass2 if x < -7 or x > 7 else grass, edge=0.22)

river_points = [(-13.0, -7.4, 0.54), (-9.2, -5.2, 0.56), (-5.4, -2.8, 0.57), (-1.4, -0.35, 0.58), (2.4, 1.85, 0.59), (6.7, 4.4, 0.60), (13.0, 7.4, 0.62)]
river_bank = tube("wide river bank", river_points, .78, stone, resolution=5)
river_obj = tube("river", river_points, .58, river, resolution=5)
river_obj.location.z = .12
river_highlight = tube("river highlight", [(-12.2, -6.9, 0.82), (-8.3, -4.9, 0.83), (-4.8, -2.55, 0.84), (-1.2, -0.3, 0.85), (2.8, 1.95, 0.86), (6.7, 4.45, 0.87), (12.2, 7.0, 0.88)], 0.038, river_glint, resolution=5)
river_highlight.location.z = .19

lanes = [
    [(-12.7, -7.4, 0.68), (-9.1, -5.25, 0.69), (-5.3, -2.5, 0.70), (-1.8, -0.28, 0.71)],
    [(-12.6, 7.25, 0.68), (-8.9, 5.1, 0.69), (-5.1, 2.55, 0.70), (-1.9, 0.54, 0.71)],
    [(12.6, -7.25, 0.68), (8.9, -5.1, 0.69), (5.1, -2.3, 0.70), (1.9, 0.48, 0.71)],
    [(12.6, 7.3, 0.68), (8.9, 5.0, 0.69), (5.15, 2.6, 0.70), (1.9, 1.92, 0.71)],
]
for index, points in enumerate(lanes):
    tube("lane bank %d" % index, points, 0.24, earth, resolution=4)
    tube("lane path %d" % index, points, 0.15, lane, resolution=4)
    tube("lane inlay %d" % index, points, 0.018, lane_line, resolution=4)


def tree(index, x, y, size):
    cylinder("tree trunk %d" % index, (x, y, 0.9 * size), 0.14 * size, 1.55 * size, basalt, vertices=10)
    for sub, (dx, dy, z) in enumerate(((0, 0, 1.55), (-0.27, 0.03, 1.25), (0.24, -0.06, 1.30))):
        sphere("tree canopy %d-%d" % (index, sub), (x + dx * size, y + dy * size, z * size), 0.63 * size, grass2 if sub == 0 else grass, scale=(1.0, 0.88, 0.82), ico=True)
    cylinder("tree crown %d" % index, (x, y, 2.14 * size), 0.34 * size, 0.72 * size, grass2, vertices=8)


trees = [(-10.0, 3.2, 1.2), (-8.0, 2.5, .82), (-6.7, 3.3, 1.05), (-8.7, 1.55, .72), (7.6, 2.9, 1.12), (9.0, 3.55, .82), (6.3, 3.85, .72), (7.0, 1.6, .88), (-5.9, -4.35, 1.0), (-4.45, -5.0, 1.15), (-3.35, -3.65, .75), (4.5, -4.6, 1.08), (5.8, -3.75, .80), (6.55, -4.9, .70), (-2.9, 3.55, .72), (3.0, -3.0, .68)]
for i, (x, y, size) in enumerate(trees):
    tree(i, x, y, size)


def rock_cluster(index, x, y, size):
    for sub in range(4):
        angle = sub * 2.2 + index * .4
        radius = size * (.22 + sub * .10)
        sphere("rock %d-%d" % (index, sub), (x + math.cos(angle) * radius, y + math.sin(angle) * radius, .62 + sub * .06), size * (.26 + (sub % 2) * .08), stone if sub else lane, scale=(1, .78, .70), ico=True)


for i, (x, y, size) in enumerate([(-4.3, 1.35, 1.25), (4.4, 1.05, 1.08), (-2.0, -2.75, .86), (2.5, 3.0, .90), (0, 5.05, .98)]):
    rock_cluster(i, x, y, size)


def tower(name, x, y, team):
    cylinder(name + " base", (x, y, .64), .74, .28, stone, vertices=14)
    cylinder(name + " shaft", (x, y, 1.23), .43, .88, lane, vertices=14)
    cylinder(name + " collar", (x, y, 1.77), .57, .14, team, vertices=14)
    cone = cylinder(name + " beacon", (x, y, 2.25), .17, .62, team, vertices=8)
    bpy.ops.object.light_add(type="POINT", location=(x, y, 2.6))
    glow = bpy.context.object
    glow.data.energy = 32
    glow.data.color = (0.08, .35, 1.0) if team == cobalt else (.55, .08, 1.0)
    glow.data.shadow_soft_size = 1.5


for i, (x, y) in enumerate([(-10.8, -6.6), (-7.7, -5.1), (-9.4, -3.9)]):
    tower("cobalt tower %d" % i, x, y, cobalt)
for i, (x, y) in enumerate([(10.8, 6.6), (7.7, 5.1), (9.4, 3.9)]):
    tower("violet tower %d" % i, x, y, violet)


def nexus(name, x, y, team):
    cylinder(name + " platform", (x, y, .62), 1.52, .30, stone, vertices=14)
    cylinder(name + " ring", (x, y, .84), 1.08, .12, team, vertices=14)
    cylinder(name + " pedestal", (x, y, 1.1), .66, .44, lane, vertices=10)
    bpy.ops.mesh.primitive_cone_add(vertices=6, radius1=.50, radius2=.08, depth=1.28, location=(x, y, 1.86))
    put(bpy.context.object, team)


nexus("cobalt nexus", -11.2, -6.95, cobalt)
nexus("violet nexus", 11.2, 6.95, violet)


def objective(name, x, y):
    cylinder(name + " outer ring", (x, y, .50), 1.65, .18, stone, vertices=20)
    cylinder(name + " pit", (x, y, .60), 1.26, .20, earth, vertices=20)
    cylinder(name + " gold rim", (x, y, .72), .95, .12, gold, vertices=20)
    sphere(name + " crystal", (x, y, 1.35), .46, crystal, scale=(1, 1, 1.4), ico=True)


objective("dragon pit", 4.1, .95)
objective("baron pit", -4.05, .85)
for i, (x, y) in enumerate([(-1.55, -.22), (.2, .9), (1.9, 1.8), (-2.05, -1.1)]):
    cylinder("river rune %d" % i, (x, y, .92), .22, .50, lane, vertices=8)
    cylinder("river rune light %d" % i, (x, y, 1.22), .12, .16, crystal, vertices=6)

# Framing stones and banners keep the diagonal legible at a glance.
for i, x in enumerate((-11, -7.5, -3.2, 3.3, 7.5, 11)):
    rock_cluster(20 + i, x, -8.55, .66 + (i % 2) * .15)
for i, (x, y, team) in enumerate(((-12.45, 3.65, cobalt), (12.45, -3.65, violet))):
    cube("banner pole %d" % i, (x, y, 2.15), (.06, .06, 2.0), stone, edge=.04)
    cube("banner cloth %d" % i, (x + (.36 if i == 0 else -.36), y, 3.05), (.4, .04, .54), team, rotation=math.radians(-8 if i == 0 else 8), edge=.04)

# Camera has no depth-of-field: all geometry remains crisp at UI scale.
bpy.ops.object.camera_add(location=(20.8, -23.2, 19.0))
camera = bpy.context.object
camera.data.type = "PERSP"
camera.data.lens = 56
camera.data.dof.use_dof = False
look_at(camera, (0, .35, .6))
bpy.context.scene.camera = camera

light("cool key", (-9, -10, 18), (.55, .76, 1.0), 1800, 10)
light("aqua fill", (8, 6, 15), (.22, .60, .95), 1350, 9)
light("warm gold fill", (0, 8, 10), (1.0, .52, .20), 620, 7)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 3840
scene.render.resolution_y = 2160
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "16"
scene.render.filepath = OUT
scene.render.film_transparent = False
scene.world.color = (.004, .009, .018)
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast"
bpy.context.scene.world.use_nodes = True
world_bg = bpy.context.scene.world.node_tree.nodes.get("Background")
world_bg.inputs["Color"].default_value = (.002, .008, .022, 1)
world_bg.inputs["Strength"].default_value = 0.18
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
bpy.ops.render.render(write_still=True)
