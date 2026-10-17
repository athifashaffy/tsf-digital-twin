"""
make_parts.py — generates the printable parts for the TSF lab rig.

    python make_parts.py          → stl/*.stl (print orientation) + assembly.glb (viewer)

Units are millimetres. Everything that depends on a bought part is a constant at
the top; measure your parts and change them before printing.
"""
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import CrossSection, JoinType, Manifold

OUT = Path(__file__).parent
SEG = 64

# ── Bought-part dimensions (measure and adjust) ──────────────────────────────
BAR = 20.0          # square bar laid across the tank (aluminium tube or wooden strip)
FIT = 0.6           # clearance added to the bar for sliding fits
GLAND_D = 12.5      # PG7 cable gland thread hole
SONAR_CAN = 16.0    # HC-SR04 transducer diameter
TANK = (400, 300, 290)  # viewer only: tank inner length, width, height

# ── Box ──────────────────────────────────────────────────────────────────────
IN_L, IN_W, IN_H = 170.0, 110.0, 60.0
WALL, FLOOR, LID_T = 3.0, 2.5, 3.0
OUT_L, OUT_W = IN_L + 2 * WALL, IN_W + 2 * WALL
H = FLOOR + IN_H                        # base height (62.5)
CORNER = [(sx * 81, sy * 51) for sx in (-1, 1) for sy in (-1, 1)]
BOARD_X0, BOARD_Y0 = -83.0, -50.0       # Arduino lower-left corner (USB/jack edge on the left wall)
UNO_HOLES = [(13.97, 2.54), (15.24, 50.8), (66.04, 7.62), (66.04, 35.56)]
STANDOFF_H = 6.0
LCD_C = (38.0, -5.0)                    # LCD centre, over the breadboard
BUZZ_C = (60.0, 38.0)
SADDLE_HOLES = [(sx * 30, sy * 10) for sx in (-1, 1) for sy in (-1, 1)]


def box(x, y, z, center=False):
    return Manifold.cube([x, y, z], center=center)


def cyl(h, r, center=False, seg=SEG):
    return Manifold.cylinder(h, r, r, seg, center)


def rounded_rect(l, w, r, h):
    return CrossSection.square([l - 2 * r, w - 2 * r], True).offset(r, JoinType.Round, 2.0, SEG).extrude(h)


def union(parts):
    out = parts[0]
    for p in parts[1:]:
        out = out + p
    return out


# ── Box base (prints floor-down as modelled) ─────────────────────────────────
def make_base():
    shell = rounded_rect(OUT_L, OUT_W, 4, H) - box(IN_L, IN_W, IN_H + 1, True).translate([0, 0, FLOOR + (IN_H + 1) / 2])
    bosses = union([cyl(IN_H, 5).translate([x, y, FLOOR]) for x, y in CORNER])
    standoffs = union([cyl(STANDOFF_H, 3).translate([BOARD_X0 + hx, BOARD_Y0 + hy, FLOOR]) for hx, hy in UNO_HOLES])
    # breadboard retaining frame (83 × 56 board)
    frame = box(86, 59, 2, True) - box(83.4, 56.4, 3, True)
    frame = frame.translate([38, -5, FLOOR + 1])
    body = shell + bosses + standoffs + frame

    cuts = []
    cuts += [cyl(16, 1.4).translate([x, y, H - 15]) for x, y in CORNER]                     # M3 self-tap, lid screws
    cuts += [cyl(6, 1.4).translate([BOARD_X0 + hx, BOARD_Y0 + hy, FLOOR + 1]) for hx, hy in UNO_HOLES]
    cuts += [cyl(FLOOR + 2, 1.7).translate([x, y, -1]) for x, y in SADDLE_HOLES]             # M3 to saddle
    # left wall: one window for USB-C and the DC jack
    cuts.append(box(10, 48, 14, True).translate([-IN_L / 2 - WALL / 2, -24, FLOOR + STANDOFF_H + 8]))
    # right wall: 4 glands — LEVEL, FLOW, TURB, STRIP
    for y in (-33, -11, 11, 33):
        cuts.append(cyl(10, GLAND_D / 2).rotate([0, 90, 0]).translate([IN_L / 2 - 2, y, 32]))
    # back wall: 1 gland — pump / aux
    cuts.append(cyl(10, GLAND_D / 2).rotate([90, 0, 0]).translate([60, IN_W / 2 + 5, 32]))
    # front wall: IR receiver window
    cuts.append(cyl(10, 3).rotate([90, 0, 0]).translate([-40, -IN_W / 2 + 2, 42]))
    return body - union(cuts)


# ── Lid (modelled in place; flipped for printing) ────────────────────────────
def make_lid():
    plate = rounded_rect(OUT_L, OUT_W, 4, LID_T)
    lip_o = box(IN_L - 0.8, IN_W - 0.8, 4, True) - box(IN_L - 3.8, IN_W - 3.8, 5, True)
    for x, y in CORNER:
        lip_o = lip_o - box(14, 14, 6, True).translate([x, y, 0])
    lip = lip_o.translate([0, 0, -2])
    lx, ly = LCD_C
    lcd_bosses = union([cyl(4, 3).translate([lx + sx * 37.5, ly + sy * 15.5, -4]) for sx in (-1, 1) for sy in (-1, 1)])
    bx, by = BUZZ_C
    buzz_ring = (cyl(5, 7.7) - cyl(6, 6.2).translate([0, 0, -0.5])).translate([bx, by, -5])
    body = plate + lip + lcd_bosses + buzz_ring

    cuts = [box(72, 25, 10, True).translate([lx, ly, 0])]                                      # LCD bezel
    cuts += [cyl(10, 1.7).translate([lx + sx * 37.5, ly + sy * 15.5, -6]) for sx in (-1, 1) for sy in (-1, 1)]
    cuts += [cyl(10, 1.7).translate([x, y, -2]) for x, y in CORNER]                          # lid screws
    cuts += [cyl(10, 3.0).translate([x, y, LID_T - 1.6]) for x, y in CORNER]                 # screw-head counterbore
    for dx, dy in [(0, 0), (-4, 0), (4, 0), (-2, 3.5), (2, 3.5), (-2, -3.5), (2, -3.5)]:
        cuts.append(cyl(10, 1.0, seg=24).translate([bx + dx, by + dy, -2]))                   # buzzer grille
    return body - union(cuts)


# ── Saddle: bolts under the box, grips the bar (prints plate-down) ───────────
def make_saddle():
    plate = box(90, 36, 4).translate([-45, -18, -4])
    g = BAR + FIT
    walls = (box(36, g + 8, BAR + 7).translate([-18, -(g + 8) / 2, -4 - (BAR + 7)])
             - box(40, g, BAR + 8).translate([-20, -g / 2, -4 - (BAR + 8)]))
    body = plate + walls
    cuts = [cyl(6, 1.7).translate([x, y, -5]) for x, y in SADDLE_HOLES]
    cuts += [cyl(6, 3.3, seg=6).translate([x, y, -5]) for x, y in SADDLE_HOLES]               # M3 nut traps
    cuts.append(cyl(g + 20, 2.2).rotate([90, 0, 0]).translate([0, (g + 20) / 2, -4 - BAR - 3.5]))  # M4 bolt under bar
    return body - union(cuts)


def sleeve(length=30):
    g = BAR + FIT
    o = g + 7
    s = box(length, o, o, True) - box(length + 2, g, g, True)
    return s - cyl(10, 1.7).translate([0, 0, g / 2 - 1])                                     # M4 thumb-screw, self-tap


# ── Rim clamp: slides on the bar, finger rests on the tank's inner wall ──────
def make_clamp():
    o = BAR + FIT + 7
    finger = box(4, o, 43).translate([11, -o / 2, -o / 2 - 40])        # hangs below the sleeve, channel stays open
    return sleeve() + finger


# ── HC-SR04 holder: sensor sits on the plate, transducers face down ──────────
def make_sonar():
    o = BAR + FIT + 7
    zb = -o / 2
    arm = box(14, 34, 8).translate([-7, o / 2 - 2, zb])
    plate = box(54, 28, 3).translate([-27, o / 2 + 30, zb])
    lip = box(54, 28, 2).translate([-27, o / 2 + 30, zb + 3]) - box(46, 21, 4).translate([-23, o / 2 + 33.5, zb + 2])
    lip = lip - box(14, 6, 4).translate([-7, o / 2 + 52, zb + 2])                            # header pins gap
    body = sleeve() + arm + plate + lip
    cy = o / 2 + 44
    cuts = [CrossSection.square([4.5, 0.01], True).offset(SONAR_CAN / 2 + 0.6, JoinType.Round, 2.0, SEG)
            .extrude(10).translate([sx * 13, cy, zb - 1]) for sx in (-1, 1)]                  # oblong: fits 24–29 mm pitch
    return body - union(cuts)


# ── Probe hanger: flat arm with zip-tie slots, hangs into the water ──────────
def make_hanger(length=170):
    o = BAR + FIT + 7
    arm = box(18, 4, length).translate([-9, o / 2, o / 2 - length])
    body = sleeve() + arm
    cuts = []
    for z in np.arange(o / 2 - 30, o / 2 - length + 6, -12):
        for x in (-5, 5):
            cuts.append(box(2.6, 10, 4.5).translate([x - 1.3, o / 2 - 3, z]))
    return body - union(cuts)


# ── Flow-meter cradle: YF-S201 body tied into a U-channel ────────────────────
def make_cradle():
    base = box(70, 44, 3).translate([-35, -22, 0])
    walls = box(40, 44, 14).translate([-20, -22, 3]) - box(42, 36, 15).translate([-21, -18, 3])
    body = base + walls
    cuts = [cyl(5, 2.2).translate([sx * 28, 0, -1]) for sx in (-1, 1)]
    for x in (-12, 12):
        cuts.append(box(4, 50, 2.6).translate([x - 2, -25, 8]))
    return body - union(cuts)


# ── Export helpers ───────────────────────────────────────────────────────────
def to_trimesh(m):
    mesh = m.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=True)


def on_bed(m):
    lo = np.asarray(m.bounding_box()[:3])
    hi = np.asarray(m.bounding_box()[3:])
    c = (lo + hi) / 2
    return m.translate([-c[0], -c[1], -lo[2]])


def main():
    parts = {
        "box_base": make_base(), "box_lid": make_lid(), "saddle": make_saddle(), "rim_clamp": make_clamp(),
        "sonar_holder": make_sonar(), "probe_hanger": make_hanger(), "flow_cradle": make_cradle(),
    }
    for name, m in parts.items():
        if m.is_empty():
            raise SystemExit(f"{name} came out empty")

    # print orientation
    printable = {
        "box_base": parts["box_base"],
        "box_lid": parts["box_lid"].rotate([180, 0, 0]),
        "saddle": parts["saddle"].rotate([180, 0, 0]),
        "rim_clamp_x2": parts["rim_clamp"].rotate([0, 90, 0]),
        "sonar_holder": parts["sonar_holder"],
        "probe_hanger_x2": parts["probe_hanger"].rotate([-90, 0, 0]),
        "flow_cradle": parts["flow_cradle"],
    }
    (OUT / "stl").mkdir(exist_ok=True)
    for name, m in printable.items():
        m = on_bed(m)
        t = to_trimesh(m)
        t.export(OUT / "stl" / f"{name}.stl")
        bb = np.ptp(t.bounds, axis=0)
        print(f"{name:18s} {bb[0]:6.1f} × {bb[1]:6.1f} × {bb[2]:6.1f} mm  watertight={t.is_watertight}  vol={t.volume/1000:6.1f} cm³")

    # assembly for the web viewer (bar along x on the tank rim at z = 0)
    zc = BAR / 2
    sad_top = BAR + 4
    tl, tw, th = TANK
    asm = [
        ("tank", to_trimesh(box(tl + 6, tw + 6, th).translate([-(tl + 6) / 2, -(tw + 6) / 2, -th])
                            - box(tl, tw, th).translate([-tl / 2, -tw / 2, -th + 3])), "#cfe3f1"),
        ("water", to_trimesh(box(tl - 1, tw - 1, 1).translate([-(tl - 1) / 2, -(tw - 1) / 2, -150])), "#4f8fc4"),
        ("bar", to_trimesh(box(tl + 70, BAR, BAR).translate([-(tl + 70) / 2, -BAR / 2, 0])), "#9aa0a6"),
        ("saddle", to_trimesh(parts["saddle"].translate([0, 0, sad_top])), "#e07a2f"),
        ("box_base", to_trimesh(parts["box_base"].translate([0, 0, sad_top])), "#5d6b78"),
        ("box_lid", to_trimesh(parts["box_lid"].translate([0, 0, sad_top + H])), "#6c7b88"),
        ("clamp_l", to_trimesh(parts["rim_clamp"].rotate([0, 0, 180]).translate([-tl / 2 + 15, 0, zc])), "#e07a2f"),
        ("clamp_r", to_trimesh(parts["rim_clamp"].translate([tl / 2 - 15, 0, zc])), "#e07a2f"),
        ("sonar_holder", to_trimesh(parts["sonar_holder"].translate([-120, 0, zc])), "#e07a2f"),
        ("hanger_turb", to_trimesh(parts["probe_hanger"].translate([120, 0, zc])), "#e07a2f"),
        ("hanger_strip", to_trimesh(parts["probe_hanger"].translate([155, 0, zc])), "#e07a2f"),
        ("flow_cradle", to_trimesh(parts["flow_cradle"].translate([tl / 2 + 70, 0, -th])), "#e07a2f"),
    ]
    # web viewer reads raw float32 positions + uint32 indices per part (base64) — no glTF loader needed
    import base64, json
    web = []
    for name, t, color in asm:
        web.append({"name": name, "color": color,
                    "p": base64.b64encode(np.asarray(t.vertices, dtype="<f4").tobytes()).decode(),
                    "i": base64.b64encode(np.asarray(t.faces, dtype="<u4").tobytes()).decode()})
    (OUT / "assembly.json").write_text(json.dumps(web))
    print("assembly.json written")


if __name__ == "__main__":
    main()
