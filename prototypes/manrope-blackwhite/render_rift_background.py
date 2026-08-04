"""Render the full-colour, 4K Rift atmosphere used by the prototype.

The generated plate is treated as a matte backplate and lightly blended with the
earlier local Rift render for depth continuity. The colour grade stays vivid so
the browser can use the environment as atmosphere instead of flattening it.
"""

from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parent
PLATE = ROOT / "assets" / "rift-imagegen-plate-color-v4-4k-source.png"
BASE = ROOT / "assets" / "rift-render-base.png"
OUTPUT = ROOT / "assets" / "rift-blender-bg-4k-v4.png"


def image(path: Path):
    return bpy.data.images.load(str(path), check_existing=True)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def build_backplate():
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, 0))
    plane = bpy.context.object
    plane.name = "Rift atmosphere backplate"
    plane.scale = (8.0, 4.5, 1.0)

    material = bpy.data.materials.new("Colour Rift matte")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    mix = nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    # Keep the generated plate at native render resolution. The older local
    # plate is intentionally not mixed into this pass because its lower
    # resolution was the source of the visible softness.
    mix.inputs[0].default_value = 0.0
    plate = nodes.new("ShaderNodeTexImage")
    plate.image = image(PLATE)
    plate.interpolation = "Cubic"
    base = nodes.new("ShaderNodeTexImage")
    base.image = image(BASE)
    base.interpolation = "Cubic"
    links.new(plate.outputs["Color"], mix.inputs[1])
    links.new(base.outputs["Color"], mix.inputs[2])
    grade = nodes.new("ShaderNodeHueSaturation")
    grade.inputs["Saturation"].default_value = 1.0
    grade.inputs["Value"].default_value = 1.0
    links.new(mix.outputs["Color"], grade.inputs["Color"])
    links.new(grade.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    plane.data.materials.append(material)


def build_camera_and_light():
    bpy.ops.object.camera_add(location=(0, 0, 10))
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 9.0
    camera.rotation_euler = (0, 0, 0)
    bpy.context.scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(0, 0, 7))
    light = bpy.context.object
    light.name = "Soft daylight"
    light.data.energy = 850
    light.data.shape = "DISK"
    light.data.size = 8


def configure_compositor(scene):
    # The source plate is already prepared at 3840×2160 with a restrained
    # Lanczos + UnsharpMask pass. Keeping the render graph material-only avoids
    # Blender 5.2's experimental compositor output nodes and keeps the .blend
    # portable across the installed LTS builds.
    return


def main():
    clear_scene()
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 3840
    scene.render.resolution_y = 2160
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.filepath = str(OUTPUT)
    scene.world.color = (0.004, 0.006, 0.007)
    scene.view_settings.view_transform = "Standard"
    build_backplate()
    build_camera_and_light()
    configure_compositor(scene)
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "rift-background-4k-v4.blend"))
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
