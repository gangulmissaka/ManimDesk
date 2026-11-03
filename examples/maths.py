"""Maths examples for ManimDesk. Open this file in the app and pick a scene."""

from manim import *
import numpy as np


class Pythagoras(Scene):
    def construct(self):
        title = Tex("Pythagorean Theorem").to_edge(UP)
        tri = Polygon(ORIGIN, 3 * RIGHT, 3 * RIGHT + 2 * UP, color=BLUE).move_to(LEFT * 2)
        eq = MathTex("a^2", "+", "b^2", "=", "c^2").scale(1.5).next_to(tri, RIGHT, buff=1)
        eq[0].set_color(YELLOW)
        eq[2].set_color(GREEN)
        eq[4].set_color(RED)
        self.play(Write(title))
        self.play(Create(tri))
        self.play(Write(eq))
        self.wait()


class SineFrequency(Scene):
    def construct(self):
        axes = Axes(x_range=[0, 2 * PI, PI / 2], y_range=[-1.5, 1.5, 0.5], x_length=7, tips=False)
        k = ValueTracker(1)
        graph = always_redraw(
            lambda: axes.plot(lambda t: np.sin(k.get_value() * t), color=YELLOW)
        )
        label = always_redraw(
            lambda: MathTex(rf"\sin({k.get_value():.1f}\,t)").next_to(axes, UP)
        )
        self.play(Create(axes), Create(graph), Write(label))
        self.play(k.animate.set_value(3), run_time=3)
        self.wait()


class Surface3D(ThreeDScene):
    def construct(self):
        axes = ThreeDAxes()
        surf = Surface(
            lambda u, v: axes.c2p(u, v, np.sin(u) * np.cos(v)),
            u_range=[-PI, PI], v_range=[-PI, PI], resolution=(24, 24),
        )
        surf.set_fill_by_checkerboard(BLUE_D, BLUE_E, opacity=0.8)
        self.set_camera_orientation(phi=65 * DEGREES, theta=-45 * DEGREES)
        self.play(Create(axes), Create(surf))
        self.begin_ambient_camera_rotation(rate=0.3)
        self.wait(3)
