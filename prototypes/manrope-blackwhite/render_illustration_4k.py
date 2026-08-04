import bpy
from pathlib import Path


root = Path(__file__).resolve().parent
source_path = root / "assets/rift-illustration-4k.png"
render_path = root / "assets/rift-illustration-blender-4k.png"
blend_path = root / "assets/rift-illustration-blender-4k.blend"

bpy.ops.wm.read_factory_settings(use_empty=True)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 3840
scene.render.resolution_y = 2160
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.render.filepath = str(render_path)
world = bpy.data.worlds.new("Illustration World")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.015, 0.025, 0.022, 1.0)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.1
scene.world = world

camera_data = bpy.data.cameras.new("Illustration Camera")
camera = bpy.data.objects.new("Illustration Camera", camera_data)
bpy.context.collection.objects.link(camera)
camera.location = (0.0, 0.0, 10.0)
camera.rotation_euler = (0.0, 0.0, 0.0)
camera_data.type = "ORTHO"
camera_data.ortho_scale = 16.0
scene.camera = camera

bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0.0, 0.0, 0.0))
plane = bpy.context.object
plane.name = "Custom Rift Illustration"
plane.scale = (8.0, 4.5, 1.0)

image = bpy.data.images.load(str(source_path), check_existing=True)
material = bpy.data.materials.new("Illustration Emission")
material.use_nodes = True
nodes = material.node_tree.nodes
links = material.node_tree.links
nodes.clear()
texture = nodes.new("ShaderNodeTexImage")
texture.image = image
texture.interpolation = "Linear"
texture.extension = "CLIP"
emission = nodes.new("ShaderNodeEmission")
emission.inputs["Strength"].default_value = 1.0
output = nodes.new("ShaderNodeOutputMaterial")
links.new(texture.outputs["Color"], emission.inputs["Color"])
links.new(emission.outputs["Emission"], output.inputs["Surface"])
plane.data.materials.append(material)

scene.view_settings.look = "AgX - Medium High Contrast"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma = 1.0

bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
bpy.ops.render.render(write_still=True)
print(render_path)
