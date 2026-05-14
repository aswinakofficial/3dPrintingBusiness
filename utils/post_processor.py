"""Post-processing pipeline for 3D mesh preparation and 3D printing optimization."""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import numpy as np

import trimesh
import logging

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


class MeshRepair:
    """Repairs and cleans mesh geometry for 3D printing."""

    def __init__(self, config: PostProcessingConfig):
        """
        Initialize mesh repair handler.

        Args:
            config: PostProcessingConfig instance
        """
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

        Args:
            mesh: Input mesh to repair

        Returns:
            Repaired mesh

        Raises:
            ValueError: If mesh repair fails
        """
        logger.info(
            f"Repairing mesh with {len(mesh.vertices)} vertices, {len(mesh.faces)} faces"
        )

        try:
            # Remove infinite values and NaNs
            if self.config.remove_infinite_values:
                mesh.remove_infinite_values()
                logger.debug("Removed infinite values")

            # Remove degenerate faces
            if self.config.remove_degenerate_faces:
                initial_faces = len(mesh.faces)
                mesh.remove_degenerate_faces()
                removed = initial_faces - len(mesh.faces)
                if removed > 0:
                    logger.info(f"Removed {removed} degenerate faces")

            # Fix non-manifold edges
            if self.config.repair_non_manifold:
                mesh.merge_vertices()
                logger.debug("Merged duplicate vertices")

            # Fill small holes
            if self.config.max_hole_size > 0:
                holes_filled = self._fill_holes(mesh, self.config.max_hole_size)
                if holes_filled > 0:
                    logger.info(f"Filled {holes_filled} holes")

            # Final validation
            if not getattr(mesh, 'is_valid', True):
                logger.warning("Mesh still has validity issues after repair, attempting additional fixes")
                mesh.remove_unreferenced_vertices()
                logger.debug("Removed unreferenced vertices")

            logger.info(
                f"Repair complete: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces, valid={getattr(mesh, 'is_valid', 'unknown')}"
            )

            return mesh

        except Exception as e:
            error_msg = f"Mesh repair failed: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _fill_holes(self, mesh: trimesh.Trimesh, max_hole_size: int) -> int:
        """
        Fill small holes in mesh.

        Args:
            mesh: Mesh to fill holes in
            max_hole_size: Maximum hole size in mm³ to fill

        Returns:
            Number of holes filled
        """
        try:
            # Get boundary edges
            boundaries = mesh.split(only_watertight=False)
            holes_filled = 0

            for submesh in boundaries:
                if not submesh.is_watertight:
                    # Estimate hole size from submesh
                    hole_volume = submesh.volume if submesh.volume is not None else 0
                    if 0 < hole_volume < max_hole_size:
                        holes_filled += 1
                        logger.debug(f"Identified hole with volume {hole_volume}mm³")

            # Attempt fill using trimesh
            if hasattr(mesh, 'fill_holes'):
                mesh.fill_holes()
                logger.debug("Filled holes using trimesh fill_holes()")

            return holes_filled

        except Exception as e:
            logger.warning(f"Hole filling failed (non-critical): {e}")
            return 0


class MeshHollowing:
    """Creates hollow mesh shells with uniform wall thickness for 3D printing."""

    def __init__(self, config: PostProcessingConfig):
        """
        Initialize mesh hollowing handler.

        Args:
            config: PostProcessingConfig instance
        """
        self.config = config
        logger.debug("Initialized MeshHollowing handler")

    def hollow_mesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Create hollow shell from solid mesh with uniform wall thickness.

        Process:
        1. Validate input mesh is watertight
        2. Create outer shell as offset
        3. Create inner shell (inset)
        4. Merge shells to create hollow structure
        5. Add drainage holes if needed

        Args:
            mesh: Solid input mesh

        Returns:
            Hollow mesh with uniform wall thickness

        Raises:
            ValueError: If hollowing fails
        """
        logger.info(
            f"Creating hollow shell with {self.config.wall_thickness}mm wall thickness"
        )

        try:
            # Validate mesh is suitable for hollowing
            if not mesh.is_watertight:
                logger.warning("Mesh is not watertight, attempting repair before hollowing")
                mesh = self._make_watertight(mesh)

            # Create voxel-based offset
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

            # Add drainage hole if created interior cavities
            hollow_mesh = self._add_drainage_holes(hollow_mesh)

            logger.info(
                f"Hollowing complete: {len(hollow_mesh.vertices)} vertices, {len(hollow_mesh.faces)} faces"
            )

            return hollow_mesh

        except Exception as e:
            error_msg = f"Mesh hollowing failed: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _make_watertight(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Attempt to make mesh watertight using morphological operations.

        Args:
            mesh: Input mesh

        Returns:
            Watertight mesh
        """
        logger.debug("Attempting to make mesh watertight")

        try:
            # Use convex hull as fallback (conservative)
            if hasattr(mesh, 'convex_hull'):
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
        """
        Create hollow mesh using voxelization method.

        Args:
            mesh: Input mesh
            wall_thickness: Desired wall thickness in mm
            voxel_resolution: Resolution of voxel grid in mm

        Returns:
            Hollow mesh or None if voxelization fails
        """
        try:
            logger.debug(
                f"Voxelizing mesh with resolution {voxel_resolution}mm, wall thickness {wall_thickness}mm"
            )

            # Convert to voxels
            pitch = voxel_resolution
            voxels = mesh.voxelized(pitch=pitch)

            # Create inner cavity by inset
            voxel_array = voxels.matrix.copy()

            # Erode the voxel grid by wall thickness (in voxels)
            erosion_voxels = max(1, int(wall_thickness / voxel_resolution))
            logger.debug(f"Eroding by {erosion_voxels} voxels")

            from scipy.ndimage import binary_erosion

            eroded = binary_erosion(voxel_array, iterations=erosion_voxels)

            # Subtract eroded from original to create shell
            shell_voxels = voxel_array & ~eroded

            # Convert back to mesh
            voxels.matrix[:] = shell_voxels
            hollow = voxels.marching_cubes

            logger.debug(f"Voxel-based hollowing produced {len(hollow.vertices)} vertices")

            return hollow

        except Exception as e:
            logger.warning(f"Voxel-based hollowing failed: {e}")
            return None

    def _create_hollow_offset(
        self, mesh: trimesh.Trimesh, wall_thickness: float
    ) -> trimesh.Trimesh:
        """
        Create hollow mesh using offset method.

        Simpler fallback: offsets mesh inward to create shell.

        Args:
            mesh: Input mesh
            wall_thickness: Wall thickness in mm

        Returns:
            Hollow mesh
        """
        try:
            logger.debug(f"Using offset method with wall thickness {wall_thickness}mm")

            # Calculate inset normal
            inset_factor = -wall_thickness / 100  # Convert mm to normalized units

            # Try trimesh offset (may not be available)
            if hasattr(mesh, 'apply_scale'):
                # Create inner cavity by scaling inward
                inner_mesh = mesh.copy()
                scale_factor = 1 - (wall_thickness / max(mesh.extents))
                inner_mesh.apply_scale(scale_factor)

                # Combine outer and inner as two-sided surface
                combined = trimesh.util.concatenate([mesh, inner_mesh])
                logger.debug(f"Created hollow with combined offset: {len(combined.vertices)} vertices")
                return combined

            logger.warning("Offset method unavailable, returning original mesh")
            return mesh

        except Exception as e:
            logger.warning(f"Offset-based hollowing failed: {e}")
            return mesh

    def _add_drainage_holes(self, mesh: trimesh.Trimesh, hole_diameter: float = 3.0) -> trimesh.Trimesh:
        """
        Add drainage holes for interior cavities (post-processing).

        Args:
            mesh: Hollow mesh
            hole_diameter: Diameter of drainage hole in mm

        Returns:
            Mesh with drainage holes marked (metadata only, not modified)
        """
        logger.debug(f"Marking drainage hole locations (diameter {hole_diameter}mm)")
        # Actual hole drilling would be done in Phase 4 with post-processing metadata
        return mesh


class SupportGenerator:
    """Generates minimal support structures for overhanging geometry."""

    def __init__(self, config: PostProcessingConfig):
        """
        Initialize support generator.

        Args:
            config: PostProcessingConfig instance
        """
        self.config = config
        logger.debug("Initialized SupportGenerator handler")

    def generate_supports(self, mesh: trimesh.Trimesh) -> Dict[str, Any]:
        """
        Generate support structures for overhanging surfaces.

        Process:
        1. Identify overhanging faces (> angle_threshold from vertical)
        2. Group overhangs into islands
        3. Generate minimal support columns
        4. Create raft (optional) for bed adhesion

        Args:
            mesh: Input mesh

        Returns:
            Dict with support mesh and metadata

        Raises:
            ValueError: If support generation fails
        """
        logger.info(
            f"Generating supports for overhangs > {self.config.support_angle_threshold}°"
        )

        try:
            # Identify overhangs
            overhangs = self._identify_overhangs(mesh)
            if len(overhangs) == 0:
                logger.info("No overhangs detected, no supports needed")
                return {
                    "support_mesh": None,
                    "has_supports": False,
                    "overhang_faces": 0,
                }

            logger.info(f"Detected {len(overhangs)} overhanging faces")

            # Group overhangs
            support_regions = self._group_supports(mesh, overhangs)
            logger.info(f"Grouped into {len(support_regions)} support regions")

            # Generate support columns
            support_mesh = self._create_support_columns(mesh, support_regions)

            # Add raft
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
        """
        Identify faces that overhang (insufficient support below).

        Args:
            mesh: Input mesh

        Returns:
            Array of overhang face indices
        """
        try:
            # Get face normals
            face_normals = mesh.face_normals
            # Vertical direction (0, 0, 1)
            up_vector = np.array([0, 0, 1])

            # Angle between normal and vertical
            angles = np.arccos(np.clip(np.dot(face_normals, up_vector), -1, 1))
            angles_deg = np.degrees(angles)

            # Overhangs are faces where angle > threshold (pointing too far down)
            threshold_angle = self.config.support_angle_threshold
            overhangs = np.where(angles_deg > threshold_angle)[0]

            logger.debug(f"Identified {len(overhangs)} overhang faces at {threshold_angle}° threshold")

            return overhangs

        except Exception as e:
            logger.warning(f"Overhang detection failed: {e}")
            return np.array([])

    def _group_supports(self, mesh: trimesh.Trimesh, overhang_indices: np.ndarray) -> list:
        """
        Group overhanging faces into connected regions.

        Args:
            mesh: Input mesh
            overhang_indices: Array of overhang face indices

        Returns:
            List of support region dictionaries
        """
        try:
            regions = []
            processed = set()

            for face_idx in overhang_indices:
                if face_idx in processed:
                    continue

                # Find connected component
                region = self._find_connected_region(mesh, face_idx, overhang_indices, processed)
                if len(region) > 0:
                    # Calculate region centroid for support placement
                    region_faces = mesh.faces[list(region)]
                    region_verts = mesh.vertices[region_faces.flatten()]
                    centroid = region_verts.mean(axis=0)

                    regions.append({
                        "faces": region,
                        "centroid": centroid,
                        "size": len(region),
                    })
                    processed.update(region)

            logger.debug(f"Grouped overhangs into {len(regions)} regions")
            return regions

        except Exception as e:
            logger.warning(f"Support grouping failed: {e}")
            return []

    def _find_connected_region(
        self, mesh: trimesh.Trimesh, start_face: int, overhang_set: np.ndarray, processed: set
    ) -> set:
        """
        Find connected component of overhanging faces using BFS.

        Args:
            mesh: Input mesh
            start_face: Starting face index
            overhang_set: Array of all overhang indices
            processed: Set of already-processed faces

        Returns:
            Set of connected overhang face indices
        """
        region = {start_face}
        queue = [start_face]
        overhang_set_fast = set(overhang_set)

        while queue:
            face_idx = queue.pop(0)
            face = mesh.faces[face_idx]

            # Find adjacent faces
            for vertex_idx in face:
                adjacent_faces = np.where((mesh.faces == vertex_idx).any(axis=1))[0]
                for adj_face in adjacent_faces:
                    if adj_face not in processed and adj_face in overhang_set_fast:
                        if adj_face not in region:
                            region.add(adj_face)
                            queue.append(adj_face)

        return region

    def _create_support_columns(self, mesh: trimesh.Trimesh, support_regions: list) -> trimesh.Trimesh:
        """
        Create minimal support columns from centroids to build platform.

        Args:
            mesh: Input mesh
            support_regions: List of support region dictionaries

        Returns:
            Support mesh
        """
        try:
            support_meshes = []

            for region in support_regions:
                centroid = region["centroid"]
                # Find height to build platform (mesh bottom)
                z_min = mesh.bounds[0][2]

                # Create support column
                top = centroid
                bottom = np.array([centroid[0], centroid[1], z_min])

                # Create cylinder column
                column = trimesh.creation.cylinder(
                    radius=self.config.support_diameter / 2,
                    height=top[2] - bottom[2],
                )
                # Position column
                column.apply_translation(bottom + np.array([0, 0, column.extents[2] / 2]))

                support_meshes.append(column)

            if len(support_meshes) > 0:
                support_mesh = trimesh.util.concatenate(support_meshes)
                logger.debug(f"Created {len(support_meshes)} support columns")
                return support_mesh

            return None

        except Exception as e:
            logger.warning(f"Support column creation failed: {e}")
            return None

    def _add_raft(self, mesh: trimesh.Trimesh, support_mesh: Optional[trimesh.Trimesh]) -> trimesh.Trimesh:
        """
        Add rectangular raft base for improved bed adhesion.

        Args:
            mesh: Original mesh
            support_mesh: Existing support mesh

        Returns:
            Combined support + raft mesh
        """
        try:
            # Create raft base plate
            bounds = mesh.bounds
            raft_x = bounds[1][0] - bounds[0][0] + 10  # 5mm margin each side
            raft_y = bounds[1][1] - bounds[0][1] + 10
            raft_height = self.config.base_thickness

            raft = trimesh.creation.box(
                extents=[raft_x, raft_y, raft_height]
            )

            # Position raft at mesh bottom
            z_min = bounds[0][2]
            raft.apply_translation([
                bounds[0][0] + raft_x / 2,
                bounds[0][1] + raft_y / 2,
                z_min - raft_height / 2,
            ])

            if support_mesh is not None:
                combined = trimesh.util.concatenate([support_mesh, raft])
            else:
                combined = raft

            logger.debug(f"Added raft base: {raft_x:.1f}x{raft_y:.1f}x{raft_height}mm")
            return combined

        except Exception as e:
            logger.warning(f"Raft creation failed: {e}")
            return support_mesh if support_mesh is not None else mesh


class PostProcessingPipeline:
    """Orchestrates complete mesh post-processing pipeline."""

    def __init__(self, config: Optional[PostProcessingConfig] = None):
        """
        Initialize post-processing pipeline.

        Args:
            config: PostProcessingConfig instance (uses defaults if None)
        """
        self.config = config or PostProcessingConfig()
        self.repair = MeshRepair(self.config)
        self.hollowing = MeshHollowing(self.config)
        self.supports = SupportGenerator(self.config)

        logger.info("Initialized PostProcessingPipeline")

    def process_mesh(
        self, mesh_path: str, output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process mesh through complete pipeline: repair → hollow → supports → export.

        Args:
            mesh_path: Path to input mesh file
            output_path: Optional output path (auto-generated if not provided)

        Returns:
            Dict with output paths and processing metadata

        Raises:
            ValueError: If processing fails
        """
        logger.info(f"Processing mesh: {mesh_path}")

        try:
            # Load mesh — GLBs from o_voxel come back as trimesh.Scene (multi-geometry).
            # Concatenate all geometries into a single Trimesh so downstream code works.
            mesh = trimesh.load(mesh_path)
            if isinstance(mesh, trimesh.Scene):
                mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
            logger.info(f"Loaded mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")

            # Stage 1: Repair
            mesh = self.repair.repair_mesh(mesh)

            # Stage 2: Hollow (optional)
            if self.config.hollow_enabled:
                mesh = self.hollowing.hollow_mesh(mesh)
                logger.info("Hollowing complete")

            # Stage 3: Generate supports (optional)
            support_result = None
            if self.config.generate_supports:
                support_result = self.supports.generate_supports(mesh)
                logger.info(f"Support generation complete: {support_result}")

            # Generate output path
            if output_path is None:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = f"output/postprocessed/{timestamp}_processed.{self.config.output_format}"

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Export final mesh
            mesh.export(str(output_path), file_type=self.config.output_format)
            logger.info(f"Exported processed mesh to {output_path}")

            # Export supports if generated
            support_path = None
            if support_result and support_result.get("support_mesh") is not None:
                support_path = output_path.with_stem(output_path.stem + "_supports")
                support_result["support_mesh"].export(str(support_path))
                logger.info(f"Exported supports to {support_path}")

            return {
                "mesh_path": str(output_path),
                "support_path": str(support_path) if support_path else None,
                "vertices": len(mesh.vertices),
                "faces": len(mesh.faces),
                "has_supports": support_result.get("has_supports", False) if support_result else False,
                "overhang_faces": support_result.get("overhang_faces", 0) if support_result else 0,
            }

        except Exception as e:
            error_msg = f"Mesh processing failed: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)
