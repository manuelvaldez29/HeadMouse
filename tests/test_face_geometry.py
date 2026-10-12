"""Invarianza de la señal 3D de cejas frente a la pose, con una cara sintética.

Las cejas están por delante de las comisuras de los ojos. Al inclinar la cabeza,
esa diferencia de profundidad cambia la distancia vertical proyectada: es el
mecanismo que hacía subir la señal GEOMETRIC al mirar hacia arriba.
"""
import math
import unittest
from types import SimpleNamespace
import face_geometry as fg
from face_data import FaceData
from gesture_signals import brow_signal

W, H = 640, 480
# Cara en milímetros: x a la derecha de la imagen, y hacia abajo, z hacia atrás.
BASE = {
    33: (-45, 0, 12), 133: (-15, 0, 4), 263: (45, 0, 12), 362: (15, 0, 4),
    6: (0, -2, -8), 2: (0, 45, -14), 1: (0, 35, -30),
    234: (-70, 20, 60), 454: (70, 20, 60),
    **{i: (-50 + 9 * k, -22, -4) for k, i in enumerate(fg.BROW_LEFT)},
    **{i: (14 + 9 * k, -22, -4) for k, i in enumerate(fg.BROW_RIGHT)},
}


def rotate(p, pitch=0, yaw=0, roll=0):
    """Pitch positivo = frente hacia atrás (mirar arriba). Grados."""
    x, y, z = p
    a = math.radians(pitch)
    y, z = y * math.cos(a) + z * math.sin(a), -y * math.sin(a) + z * math.cos(a)
    b = math.radians(yaw)
    x, z = x * math.cos(b) + z * math.sin(b), -x * math.sin(b) + z * math.cos(b)
    c = math.radians(roll)
    x, y = x * math.cos(c) - y * math.sin(c), x * math.sin(c) + y * math.cos(c)
    return x, y, z


def landmarks(raise_mm=0, distance_scale=1.0, **pose):
    """Proyección ortográfica a coordenadas normalizadas de MediaPipe."""
    points = [SimpleNamespace(x=.5, y=.5, z=0.)] * 478
    for i, (x, y, z) in BASE.items():
        if i in fg.BROW_LEFT + fg.BROW_RIGHT:
            y -= raise_mm
        x, y, z = rotate((x, y, z), **pose)
        k = 2.2 * distance_scale  # px por mm
        points[i] = SimpleNamespace(x=.5 + x * k / W, y=.45 + y * k / H, z=z * k / W)
    return points


class FaceGeometryTests(unittest.TestCase):
    def test_3d_lift_ignores_pitch_that_moves_2d_signal(self):
        rest = fg.brow_lift_3d(landmarks(), W, H)[0]
        rest_2d = fg.brow_lift_2d(landmarks())[0]
        raised = fg.brow_lift_3d(landmarks(raise_mm=6), W, H)[0]
        amplitude = raised - rest
        for pitch in (-20, -10, 10, 20):
            looking = landmarks(pitch=pitch)
            self.assertAlmostEqual(fg.brow_lift_3d(looking, W, H)[0], rest, delta=.02 * amplitude)
            drift_2d = abs(fg.brow_lift_2d(looking)[0] - rest_2d)
            amplitude_2d = fg.brow_lift_2d(landmarks(raise_mm=6))[0] - rest_2d
            self.assertGreater(drift_2d, .3 * amplitude_2d, pitch)

    def test_3d_lift_ignores_yaw_roll_and_distance(self):
        rest = fg.brow_lift_3d(landmarks(), W, H)
        for pose in ({"yaw": 25}, {"yaw": -25}, {"roll": 15}, {"pitch": 15, "yaw": 15, "roll": -10}):
            for side, value in enumerate(fg.brow_lift_3d(landmarks(**pose), W, H)):
                self.assertAlmostEqual(value, rest[side], places=6)
        for side, value in enumerate(fg.brow_lift_3d(landmarks(distance_scale=.6), W, H)):
            self.assertAlmostEqual(value, rest[side], places=6)

    def test_raise_increases_both_sides_and_sides_are_independent(self):
        rest = fg.brow_lift_3d(landmarks(), W, H)
        raised = fg.brow_lift_3d(landmarks(raise_mm=6, pitch=15), W, H)
        self.assertGreater(raised[0], rest[0] + .05)
        self.assertGreater(raised[1], rest[1] + .05)
        self.assertGreater(rest[0], 0)

    def test_head_pose_signs(self):
        # El pitch absoluto incluye la inclinación anatómica del tabique; se usa relativo al reposo.
        rest_pitch = fg.head_pose(landmarks(), W, H)[0]
        pitch, yaw, roll = fg.head_pose(landmarks(pitch=15), W, H)
        self.assertAlmostEqual(pitch - rest_pitch, 15, delta=1)
        self.assertAlmostEqual(yaw, 0, delta=1)
        self.assertAlmostEqual(fg.head_pose(landmarks(roll=10), W, H)[2], 10, delta=1)
        self.assertAlmostEqual(abs(fg.head_pose(landmarks(yaw=20), W, H)[1]), 20, delta=1)

    def test_degenerate_landmarks_return_none(self):
        flat = [SimpleNamespace(x=.5, y=.5, z=0.)] * 478
        self.assertIsNone(fg.brow_lift_3d(flat, W, H))
        self.assertIsNone(fg.head_pose(flat, W, H))
        self.assertIsNone(fg.brow_lift_2d(flat))

    def test_signal_source_uses_3d_and_reports_missing(self):
        face = FaceData(True, timestamp_ms=1, brow_left_lift=.2, brow_right_lift=.2,
                        brow_left_3d=.31, brow_right_3d=.29)
        self.assertEqual(brow_signal(face, "left", "GEOMETRIC_3D"), .31)
        self.assertIsNone(brow_signal(FaceData(True, timestamp_ms=1), "left", "GEOMETRIC_3D"))
        self.assertTrue(face.valid())
        self.assertFalse(FaceData(True, timestamp_ms=1, head_pitch=float("nan")).valid())


if __name__ == "__main__": unittest.main()
