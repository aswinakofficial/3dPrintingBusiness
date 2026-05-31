"""Post-processing pipeline for 3D mesh preparation and 3D printing optimization."""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
import numpy as np

import trimesh

from utils.logger import get_logger

logger = get_logger()


@dataclass
class PostProcessingConfig:
    """Configuration for mesh post-processing."""

    # Mesh repair settings
    repair_non_manifold: bool = True
    max_hole_size: int = 30  # mm³
    remove_degenerate_faces: bool = True
    remove_infinite_values: bool = True

    # Mesh hollowing settings
    hollow_enabled: bool = True
    wall_thickness: float = 2.0  # mm
    voxel_resolution: float = 1.0  # mm
    preserve_thickness: bool = True

    # Support generation settings
    generate_supports: bool = True
    support_angle_threshold: float = 45.0  # degrees from vertical
    support_diameter: float = 3.0  # mm
    base_thickness: float = 1.0  # mm
    raft_enabled: bool = True

    # Output settings
    output_format: str = "glb"  # glb, obj, ply, stl
    simplify_mesh: bool = False
    target_reduction: float = 0.1  # 10% reduction

    # Optimizer settings (Layer 2)
    enable_optimizer: bool = True
    target_face_count: int = 0  # 0 = auto from engine profile


class MeshRepair:
    """Repairs and cleans mesh geometry for 3D printing."""

    def __init__(self, config: PostProcessingConfig):
        self.config = config
        logger.debug("Initialized MeshRepair handler")

    def repair_mesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Repair mesh non-manifold geometry and defects.

        Steps:
        1. Remove infinite values (NaN, inf vertices)
        2. Remove degenerate faces (0-area faces)
        3. Fix non-manifold geometry
        4. Fill small holes
        5. Remove duplicate vertices
        6. Validate final mesh
        """
        logger.info(
            f"Repairing mesh with {len(mesh.vertices)} vertices, {len(mesh.faces)} faces"
        )

        try:
            if self.config.remove_infinite_values:
                mesh.remove_infinite_values()
                logger.debug("Removed infinite values")

            if self.config.remove_degenerate_faces:
                initial_faces = len(mesh.faces)
                mesh.remove_degenerate_faces()
                removed = initial_faces - len(mesh.faces)
                if removed > 0:
                    logger.info(f"Removed {removed} degenerate faces")

            if self.config.repair_non_manifold:
                mesh.merge_vertices()
                logger.debug("Merged duplicate vertices")

            if self.config.max_hole_size > 0:
                holes_filled = self._fill_holes(mesh, self.config.max_hole_size)
                if holes_filled > 0:
                    logger.info(f"Filled {holes_filled} holes")

            if not getattr(mesh, "is_valid", True):
                logger.warning(
                    "Mesh still has validity issues after repair, attempting additional fixes"
                )
                mesh.remove_unreferenced_vertices()
                logger.debug("Removed unreferenced vertices")

            logger.info(
                f"Repair complete: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces, "
                f"valid={getattr(mesh, 'is_valid', 'unknown')}"
            )

            return mesh

        except Exception as e:
            error_msg = f"Mesh repair failed: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _fill_holes(self, mesh: trimesh.Trimesh, max_hole_size: int) -> int:
        try:
            boundaries = mesh.split(only_watertight=False)
            holes_filled = 0

            for submesh in boundaries:
                if not submesh.is_watertight:
                    hole_volume = submesh.volume if submesh.volume is not None else 0
                    if 0 < hole_volume < max_hole_size:
                        holes_filled += 1
                        logger.debug(f"Identified hole with volume {hole_volume}mm³")

            if hasattr(mesh, "fill_holes"):
                mesh.fill_holes()
                logger.debug("Filled holes using trimesh fill_holes()")

            return holes_filled

        except Exception as e:
            logger.warning(f"Hole filling failed (non-critical): {e}")
            return 0


class MeshHollowing:
    """Creates hollow mesh shells with uniform wall thickness for 3D printing."""

    def __init__(self, config: PostProcessingConfig):
        self.config = config
        logger.debug("Initialized MeshHollowing handler")

    def hollow_mesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Create hollow shell from solid mesh with uniform wall thickness."""
        logger.info(
            f"Creating hollow shell with {self.config.wall_thickness}mm wall thickness"
        )

        try:
            if not mesh.is_watertight:
                logger.warning(
                    "Mesh is not watertight, attempting repair before hollowing"
                )
                mesh = self._make_watertight(mesh)

            hollow_mesh = self._create_hollow_voxel(
                mesh,
                wall_thickness=self.config.wall_thickness,
                voxel_resolution=self.config.voxel_resolution,
            )

            if hollow_mesh is None:
                logger.warning("Voxel-based hollowing failed, using offset method")
                hollow_mesh = self._create_hollow_offset(
                    mesh, wall_thickness=self.config.wall_thickness
                )

            hollow_mesh = self._add_drainage_holes(hollow_mesh)

            logger.info(
                f"Hollowing complete: {len(hollow_mesh.vertices)} vertices, "
                f"{len(hollow_mesh.faces)} faces"
            )

            return hollow_mesh

        except Exception as e:
            error_msg = f"Mesh hollowing failed: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _make_watertight(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        logger.debug("Attempting to make mesh watertight")
        try:
            if hasattr(mesh, "convex_hull"):
                hull = mesh.convex_hull
                logger.debug(f"Using convex hull: {len(hull.vertices)} vertices")
                return hull
            return mesh
        except Exception as e:
            logger.warning(f"Watertight conversion failed: {e}")
            return mesh

    def _create_hollow_voxel(
        self,
        mesh: trimesh.Trimesh,
        wall_thickness: float,
        voxel_resolution: float,
    ) -> Optional[trimesh.Trimesh]:
        try:
            logger.debug(
                f"Voxelizing mesh with resolution {voxel_resolution}mm, "
                f"wall thickness {wall_thickness}mm"
            )

            pitch = voxel_resolution
            voxels = mesh.voxelized(pitch=pitch)
            voxel_array = voxels.matrix.copy()

            erosion_voxels = max(1, int(wall_thickness / voxel_resolution))
            logger.debug(f"Eroding by {erosion_voxels} voxels")

            from scipy.ndimage import binary_erosion

            eroded = binary_erosion(voxel_array, iterations=erosion_voxels)
            shell_voxels = voxel_array & ~eroded

            voxels.matrix[:] = shell_voxels
            hollow = voxels.marching_cubes

            logger.debug(
                f"Voxel-based hollowing produced {len(hollow.vertices)} vertices"
            )

            return hollow

        except Exception as e:
            logger.warning(f"Voxel-based hollowing failed: {e}")
            return None

    def _create_hollow_offset(
        self, mesh: trimesh.Trimesh, wall_thickness: float
    ) -> trimesh.Trimesh:
        try:
            logger.debug(f"Using offset method with wall thickness {wall_thickness}mm")

            if hasattr(mesh, "apply_scale"):
                inner_mesh = mesh.copy()
                scale_factor = 1 - (wall_thickness / max(mesh.extents))
                inner_mesh.apply_scale(scale_factor)

                combined = trimesh.util.concatenate([mesh, inner_mesh])
                logger.debug(
                    f"Created hollow with combined offset: {len(combined.vertices)} vertices"
                )
                return combined

            logger.warning("Offset method unavailable, returning original mesh")
            return mesh

        except Exception as e:
            logger.warning(f"Offset-based hollowing failed: {e}")
            return mesh

    def _add_drainage_holes(
        self, mesh: trimesh.Trimesh, hole_diameter: float = 3.0
    ) -> trimesh.Trimesh:
        logger.debug(f"Marking drainage hole locations (diameter {hole_diameter}mm)")
        return mesh


class SupportGenerator:
    """Generates minimal support structures for overhanging geometry."""

    def __init__(self, config: PostProcessingConfig):
        self.config = config
        logger.debug("Initialized SupportGenerator handler")

    def generate_supports(self, mesh: trimesh.Trimesh) -> Dict[str, Any]:
        """Generate support structures for overhanging surfaces."""
        logger.info(
            f"Generating supports for overhangs > {self.config.support_angle_threshold}°"
        )

        try:
            overhangs = self._identify_overhangs(mesh)
            if len(overhangs) == 0:
                logger.info("No overhangs detected, no supports needed")
                return {
                    "support_mesh": None,
                    "has_supports": False,
                    "overhang_faces": 0,
                }

            logger.info(f"Detected {len(overhangs)} overhanging faces")

            support_regions = self._group_supports(mesh, overhangs)
            logger.info(f"Grouped into {len(support_regions)} support regions")

            support_mesh = self._create_support_columns(mesh, support_regions)

            if self.config.raft_enabled:
                support_mesh = self._add_raft(mesh, support_mesh)
                logger.debug("Added raft for bed adhesion")

            logger.info(
                f"Support generation complete: {len(support_mesh.vertices)} vertices"
            )

            return {
                "support_mesh": support_mesh,
                "has_supports": True,
                "overhang_faces": len(overhangs),
                "support_regions": len(support_regions),
            }

        except Exception as e:
            error_msg = f"Support generation failed: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _identify_overhangs(self, mesh: trimesh.Trimesh) -> np.ndarray:
        try:
            face_normals = mesh.face_normals
            up_vector = np.array([0, 0, 1])
            angles = np.arccos(np.clip(np.dot(face_normals, up_vector), -1, 1))
            angles_deg = np.degrees(angles)
            threshold_angle = self.config.support_angle_threshold
            overhangs = np.where(angles_deg > threshold_angle)[0]
            logger.debug(
                f"Identified {len(overhangs)} overhang faces at {threshold_angle}° threshold"
            )
            return overhangs
        except Exception as e:
            logger.warning(f"Overhang detection failed: {e}")
            return np.array([])

    def _group_supports(
        self, mesh: trimesh.Trimesh, overhang_indices: np.ndarray
    ) -> list:
        try:
            regions = []
            processed = set()

            for face_idx in overhang_indices:
                if face_idx in processed:
                    continue

                region = self._find_connected_region(
                    mesh, face_idx, overhang_indices, processed
                )
                if len(region) > 0:
                    region_faces = mesh.faces[list(region)]
                    region_verts = mesh.vertices[region_faces.flatten()]
                    centroid = region_verts.mean(axis=0)

                    regions.append(
                        {
                            "faces": region,
                            "centroid": centroid,
                            "size": len(region),
                        }
                    )
                    processed.update(region)

            logger.debug(f"Grouped overhangs into {len(regions)} regions")
            return regions

        except Exception as e:
            logger.warning(f"Support grouping failed: {e}")
            return []

    def _find_connected_region(
        self,
        mesh: trimesh.Trimesh,
        start_face: int,
        overhang_set: np.ndarray,
        processed: set,
    ) -> set:
        region = {start_face}
        queue = [start_face]
        overhang_set_fast = set(overhang_set)

        while queue:
            face_idx = queue.pop(0)
            face = mesh.faces[face_idx]

            for vertex_idx in face:
                adjacent_faces = np.where((mesh.faces == vertex_idx).any(axis=1))[0]
                for adj_face in adjacent_faces:
                    if adj_face not in processed and adj_face in overhang_set_fast:
                        if adj_face not in region:
                            region.add(adj_face)
                            queue.append(adj_face)

        return region

    def _create_support_columns(
        self, mesh: trimesh.Trimesh, support_regions: list
    ) -> trimesh.Trimesh:
        try:
            support_meshes = []

            for region in support_regions:
                centroid = region["centroid"]
                z_min = mesh.bounds[0][2]

                top = centroid
                bottom = np.array([centroid[0], centroid[1], z_min])

                column = trimesh.creation.cylinder(
                    radius=self.config.support_diameter / 2,
                    height=top[2] - bottom[2],
                )
                column.apply_translation(
                    bottom + np.array([0, 0, column.extents[2] / 2])
                )

                support_meshes.append(column)

            if len(support_meshes) > 0:
                support_mesh = trimesh.util.concatenate(support_meshes)
                logger.debug(f"Created {len(support_meshes)} support columns")
                return support_mesh

            return None

        except Exception as e:
            logger.warning(f"Support column creation failed: {e}")
            return None

    def _add_raft(
        self, mesh: trimesh.Trimesh, support_mesh: Optional[trimesh.Trimesh]
    ) -> trimesh.Trimesh:
        try:
            bounds = mesh.bounds
            raft_x = bounds[1][0] - bounds[0][0] + 10
            raft_y = bounds[1][1] - bounds[0][1] + 10
            raft_height = self.config.base_thickness

            raft = trimesh.creation.box(extents=[raft_x, raft_y, raft_height])

            z_min = bounds[0][2]
            raft.apply_translation(
                [
                    bounds[0][0] + raft_x / 2,
                    bounds[0][1] + raft_y / 2,
                    z_min - raft_height / 2,
                ]
            )

            if support_mesh is not None:
                combined = trimesh.util.concatenate([support_mesh, raft])
            else:
                combined = raft

            logger.debug(f"Added raft base: {raft_x:.1f}x{raft_y:.1f}x{raft_height}mm")
            return combined

        except Exception as e:
            logger.warning(f"Raft creation failed: {e}")
            return support_mesh if support_mesh is not None else mesh


class MeshOptimizer:
    """Layer 2: universal mesh cleanup — debris removal, watertight repair, decimation, smoothing."""

    ENGINE_FACE_TARGETS = {
        "trellis":      100_000,
        "meshroom":     200_000,
        "hunyuan3d":     80_000,
        "triposg":       60_000,
        "sf3d":          60_000,
        "spar3d":        60_000,
        "instantmesh":   80_000,
    }
    DEFAULT_FACE_TARGET = 80_000

    def optimize(self, mesh: trimesh.Trimesh, engine_name: str = "") -> trimesh.Trimesh:
        target = self.ENGINE_FACE_TARGETS.get(engine_name, self.DEFAULT_FACE_TARGET)
        mesh = self._keep_largest_component(mesh)
        mesh = self._repair(mesh)
        mesh = self._pymeshfix_watertight(mesh)
        mesh = self._decimate(mesh, target)
        mesh = self._smooth(mesh)
        return mesh

    def _keep_largest_component(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        try:
            components = mesh.split(only_watertight=False)
            if len(components) <= 1:
                return mesh
            largest = max(components, key=lambda m: len(m.faces))
            removed_faces = sum(len(m.faces) for m in components) - len(largest.faces)
            logger.info(
                f"Kept largest component ({len(largest.faces)} faces); "
                f"removed {len(components)-1} debris pieces ({removed_faces} faces)"
            )
            return largest
        except Exception as exc:
            logger.warning(f"Component split failed ({exc}), keeping original")
            return mesh

    def _repair(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        try:
            mesh.fix_normals()
            trimesh.repair.fill_holes(mesh)
            mesh.merge_vertices()
        except Exception as exc:
            logger.warning(f"Basic repair partially failed ({exc})")
        return mesh

    def _pymeshfix_watertight(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        try:
            import pymeshfix
            mf = pymeshfix.MeshFix(mesh.vertices, mesh.faces)
            mf.repair()
            repaired = trimesh.Trimesh(vertices=mf.v, faces=mf.f, process=False)
            logger.info(
                f"pymeshfix repair: {len(mesh.faces)} → {len(repaired.faces)} faces, "
                f"watertight={repaired.is_watertight}"
            )
            return repaired
        except ImportError:
            logger.debug("pymeshfix not installed; using trimesh hole-fill fallback")
            try:
                trimesh.repair.fill_holes(mesh)
            except Exception:
                pass
            return mesh
        except Exception as exc:
            logger.warning(f"pymeshfix failed ({exc}); keeping trimesh-repaired mesh")
            return mesh

    def _decimate(self, mesh: trimesh.Trimesh, target: int) -> trimesh.Trimesh:
        current = len(mesh.faces)
        if current <= target:
            logger.info(f"No decimation needed ({current} faces ≤ target {target})")
            return mesh
        try:
            import pyfqmr
            simplifier = pyfqmr.Simplify()
            simplifier.setMesh(mesh.vertices, mesh.faces)
            simplifier.simplify_mesh(target_count=target, aggressiveness=7, verbose=False)
            verts, faces, _ = simplifier.getMesh()
            decimated = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
            logger.info(f"pyfqmr decimation: {current} → {len(decimated.faces)} faces")
            return decimated
        except ImportError:
            logger.debug("pyfqmr not installed; using trimesh quadric decimation")
        except Exception as exc:
            logger.warning(f"pyfqmr decimation failed ({exc}); falling back to trimesh")

        try:
            ratio = target / current
            decimated = mesh.simplify_quadric_decimation(ratio)
            logger.info(
                f"trimesh decimation: {current} → {len(decimated.faces)} faces"
            )
            return decimated
        except Exception as exc:
            logger.warning(f"trimesh decimation also failed ({exc}); keeping original")
            return mesh

    def _smooth(self, mesh: trimesh.Trimesh, iterations: int = 3) -> trimesh.Trimesh:
        try:
            smoothed = trimesh.smoothing.filter_laplacian(mesh, iterations=iterations)
            logger.debug(f"Laplacian smoothing applied ({iterations} iterations)")
            return smoothed
        except Exception as exc:
            logger.debug(f"Laplacian smoothing skipped ({exc})")
            return mesh


class PrintQualityValidator:
    """Layer 4: validate mesh print-readiness and emit a structured report."""

    def validate(self, mesh: trimesh.Trimesh, engine_name: str = "") -> dict:
        try:
            components = mesh.split(only_watertight=False)
            n_components = len(components)
        except Exception:
            n_components = 1

        watertight = bool(mesh.is_watertight)

        try:
            volume_mm3 = float(mesh.volume) if watertight else None
        except Exception:
            volume_mm3 = None

        try:
            dims = mesh.extents.tolist()
        except Exception:
            dims = None

        try:
            euler = int(mesh.euler_number)
        except Exception:
            euler = None

        score = self._score(mesh, watertight, euler, n_components)
        issues = self._issues(mesh, watertight, n_components)

        report = {
            "engine": engine_name,
            "watertight": watertight,
            "volume_mm3": volume_mm3,
            "dimensions_mm": dims,
            "faces": len(mesh.faces),
            "vertices": len(mesh.vertices),
            "components": n_components,
            "euler_number": euler,
            "print_score": score,
            "issues": issues,
        }

        logger.info(
            f"Print quality: score={score}/100, watertight={watertight}, "
            f"faces={len(mesh.faces):,}, components={n_components}"
        )
        if issues:
            for issue in issues:
                logger.warning(f"  ⚠ {issue}")

        return report

    def _score(
        self,
        mesh: trimesh.Trimesh,
        watertight: bool,
        euler: Optional[int],
        components: int,
    ) -> int:
        score = 100
        if not watertight:
            score -= 40
        if euler is not None and euler != 2:
            score -= 10
        if components > 1:
            score -= min(components - 1, 3) * 5
        face_count = len(mesh.faces)
        if face_count < 5_000:
            score -= 20
        elif face_count > 500_000:
            score -= 10
        return max(0, score)

    def _issues(
        self, mesh: trimesh.Trimesh, watertight: bool, components: int
    ) -> list:
        issues = []
        if not watertight:
            issues.append("Not watertight — will not slice cleanly")
        if components > 1:
            issues.append(f"{components} disconnected components — may need cleanup")
        try:
            if not mesh.is_volume:
                issues.append("Non-manifold geometry detected")
        except Exception:
            pass
        return issues


class PostProcessingPipeline:
    """Orchestrates complete mesh post-processing pipeline."""

    def __init__(self, config: Optional[PostProcessingConfig] = None):
        self.config = config or PostProcessingConfig()
        self.repair = MeshRepair(self.config)
        self.hollowing = MeshHollowing(self.config)
        self.supports = SupportGenerator(self.config)
        self.optimizer = MeshOptimizer()
        self.validator = PrintQualityValidator()

        logger.info("Initialized PostProcessingPipeline")

    def process_mesh(
        self,
        mesh_path: str,
        output_path: Optional[str] = None,
        engine_name: str = "",
    ) -> Dict[str, Any]:
        """
        Process mesh through complete pipeline:
          Layer 2: MeshOptimizer (debris, watertight, decimate, smooth)
          Layer 3: Repair → hollow → supports
          Layer 4: PrintQualityValidator → print_report.json
          Export: final_mesh.glb + final_mesh.stl
        """
        logger.info(f"Processing mesh: {mesh_path}")

        try:
            # Load mesh — GLBs from o_voxel come back as trimesh.Scene (multi-geometry).
            # Concatenate all geometries into a single Trimesh so downstream code works.
            mesh = trimesh.load(mesh_path)
            if isinstance(mesh, trimesh.Scene):
                mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
            logger.info(
                f"Loaded mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces"
            )

            # Layer 2: MeshOptimizer — always-on
            if self.config.enable_optimizer:
                logger.info("Layer 2: MeshOptimizer")
                target = self.config.target_face_count or 0
                if target > 0:
                    # Override per-engine target with explicit config value
                    self.optimizer.ENGINE_FACE_TARGETS[engine_name] = target
                mesh = self.optimizer.optimize(mesh, engine_name)

            # Layer 3: Repair
            mesh = self.repair.repair_mesh(mesh)

            # Layer 3: Hollow (optional)
            if self.config.hollow_enabled:
                mesh = self.hollowing.hollow_mesh(mesh)
                logger.info("Hollowing complete")

            # Layer 3: Generate supports (optional)
            support_result = None
            if self.config.generate_supports:
                support_result = self.supports.generate_supports(mesh)
                logger.info(f"Support generation complete: {support_result}")

            # Generate output path
            if output_path is None:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = (
                    f"output/postprocessed/{timestamp}_processed.{self.config.output_format}"
                )

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Export final GLB
            mesh.export(str(output_path), file_type=self.config.output_format)
            logger.info(f"Exported processed mesh to {output_path}")

            # Export STL alongside the GLB
            stl_path = output_path.with_suffix(".stl")
            try:
                mesh.export(str(stl_path), file_type="stl")
                logger.info(f"Exported STL to {stl_path}")
            except Exception as exc:
                logger.warning(f"STL export failed ({exc}); GLB still available")
                stl_path = None

            # Export supports if generated
            support_path = None
            if support_result and support_result.get("support_mesh") is not None:
                support_path = output_path.with_stem(output_path.stem + "_supports")
                support_result["support_mesh"].export(str(support_path))
                logger.info(f"Exported supports to {support_path}")

            # Layer 4: PrintQualityValidator
            logger.info("Layer 4: PrintQualityValidator")
            print_report = self.validator.validate(mesh, engine_name)
            report_path = output_path.parent / "print_report.json"
            with open(report_path, "w") as f:
                json.dump(print_report, f, indent=2)
            logger.info(f"Saved print report to {report_path}")

            return {
                "mesh_path": str(output_path),
                "stl_path": str(stl_path) if stl_path else None,
                "support_path": str(support_path) if support_path else None,
                "vertices": len(mesh.vertices),
                "faces": len(mesh.faces),
                "has_supports": (
                    support_result.get("has_supports", False) if support_result else False
                ),
                "overhang_faces": (
                    support_result.get("overhang_faces", 0) if support_result else 0
                ),
                "print_report": print_report,
            }

        except Exception as e:
            error_msg = f"Mesh processing failed: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)
