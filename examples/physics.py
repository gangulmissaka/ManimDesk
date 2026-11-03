"""Physics examples for ManimDesk. Open this file in the app and pick a scene."""

from manim import *
import numpy as np


class Projectile(Scene):
    """Projectile launched at 45 degrees, ignoring air resistance."""

    def construct(self):
        g, v0, angle = 9.8, 10.0, 45 * DEGREES
        vx, vy = v0 * np.cos(angle), v0 * np.sin(angle)
        t_flight = 2 * vy / g

        axes = Axes(x_range=[0, 11, 1], y_range=[0, 3, 1], x_length=10, y_length=3.5, tips=False)
        axes.to_edge(DOWN)
        path = axes.plot_parametric_curve(
            lambda t: np.array([vx * t, vy * t - 0.5 * g * t**2]),
            t_range=[0, t_flight], color=YELLOW,
        )
        ball = Dot(axes.c2p(0, 0), color=RED, radius=0.12)
        eq = MathTex(r"y = x\tan\theta - \frac{g x^2}{2 v_0^2 \cos^2\theta}").to_edge(UP)

        self.play(Create(axes), Write(eq))
        self.add(ball)
        self.play(MoveAlongPath(ball, path), Create(path), run_time=t_flight, rate_func=linear)
        self.wait()


class Pendulum(Scene):
    """Simple pendulum solved with small time steps."""

    def construct(self):
        length, g = 3.0, 9.8
        theta = ValueTracker(60 * DEGREES)
        omega = [0.0]
        pivot = UP * 2.5

        def bob_pos():
            a = theta.get_value()
            return pivot + length * np.array([np.sin(a), -np.cos(a), 0])

        rod = always_redraw(lambda: Line(pivot, bob_pos(), color=GREY_B))
        bob = always_redraw(lambda: Dot(bob_pos(), radius=0.2, color=BLUE))
        trace = TracedPath(lambda: bob_pos(), stroke_color=BLUE_E, dissipating_time=1.5)

        def step(_mob, dt):
            omega[0] += -(g / length) * np.sin(theta.get_value()) * dt
            theta.increment_value(omega[0] * dt)

        self.add(Dot(pivot, radius=0.06), rod, trace, bob)
        theta.add_updater(step)
        self.add(theta)
        self.wait(6)
