import random

from sc2.position import Point2
from sc2.constants import UnitTypeId
from modubot.common import BasePlanner, list_flatten

_2X2_OFFSETS = [
  Point2([0, 0]),
  Point2([0, 1]),
  Point2([1, 1]),
  Point2([1, 0])
]
_3X3_OFFSETS = _2X2_OFFSETS + [
  Point2([0, -1]),
  Point2([1, -1]),
  Point2([-1, -1]),
  Point2([-1, 1]),
  Point2([-1, 0])
]

pylon_positions = [
  # RED
  [ Point2([ 5.5, 4.5 ]),
    Point2([ 7.5, 1.5 ]), ],
  # YELLOW
  [ Point2([ 5.5, 4.5 ]),
    Point2([ 2.5, 7.5 ]), ],
  # CORAL BLUE
  [ Point2([ 9.5, 1.5 ]),
    Point2([ 11.5, 1.5 ]) ],
  # AQUA
  [ Point2([ 2.5, 9.5 ]),
    Point2([ 2.5, 11.5 ]) ],
  # BLUE
  [ Point2([ 12.5, 10.5 ]),
    Point2([ 12.5, 8.5 ]) ],
  # PINK
  [ Point2([ 12.5, 10.5 ]),
    Point2([ 12.5, 12.5 ]) ],
  # ORANGE
  [ Point2([ 2.5, 15.5 ]),
    Point2([ 5.5, 17.5 ]) ],
  # UGLY GREEN
  [ Point2([ 15.5, 1.5 ]),
    Point2([ 17.5, 4.5 ])]
]

# STRUCTURE POSITIONS ARE CENTERED
structure_positions = [
  # RED
  [ Point2([ 5, 2 ]),
    Point2([ 8, 4 ]) ],
  # YELLOW
  [ Point2([ 3, 5 ]),
    Point2([ 5, 8 ]) ],
  # CORAL BLUE
  [ Point2([ 11, 4 ]) ],
  # AQUA
  [ Point2([ 5, 11 ]) ],
  # BLUE
  [ Point2([ 10, 9 ]),
    Point2([ 10, 12 ]) ],
  # PINK
  [ Point2([ 15, 12 ]),
    Point2([ 15, 9 ]) ],
  # ORANGE
  [ Point2([ 3, 18 ]),
    Point2([ 5, 15 ]) ],
  # UGLY GREEN
  [ Point2([ 15, 4 ]),
    Point2([ 18, 2 ]) ]
]

def identity(point, size=2):
  return point
def rotate_right(point, size=2):
  return Point2([ point.y, -point.x ])
def rotate_left(point, size=2):
  return Point2([ -point.y, point.x ])
def flip_both(point, size=2):
  return Point2([ -point.x, -point.y ])

mutators = [ identity, rotate_left, rotate_right, flip_both ]
god_pylons = [ mutate(Point2([ 5.5, 4.5 ])) for mutate in mutators ]

class ProtossBasePlan():
  def __init__(self):
    self.pylon_positions = []
    self.structure_positions = []

class ProtossBasePlanner(BasePlanner):
  def __init__(self, bot):
    super().__init__(bot)
    return

  async def increase_buildable_area(self, workers):
    if not self.already_pending(UnitTypeId.PYLON):
      targets = self.planner.get_available_positions(UnitTypeId.PYLON)
      for location in targets:
        can_build = await self.can_place(UnitTypeId.PYLON, location)
        if can_build:
          print("-> Force-built pylon.")
          return workers.closest_to(location).build(UnitTypeId.PYLON, location)
      print("-> Failed to force-build pylon.")
    else:
      print("-> Pylon already pending.")

  def may_place(self, structure_type):
    return self.structures(UnitTypeId.PYLON).ready.exists or structure_type in [UnitTypeId.PYLON, UnitTypeId.NEXUS]

  def can_place_pylon(self, location, desired_height):
    resources = [ g.position for g in (self.vespene_geyser + self.mineral_field) ]
    ramps = self.game_info.map_ramps
    return all(self.in_placement_grid(pos) and abs(self.get_terrain_height(pos) - desired_height) < 0.5 and all(r.is_further_than(1.0, pos) for r in resources) and all(all(point.is_further_than(1.0, pos) for point in r.points) for r in ramps) for pos in [ offset + location for offset in _2X2_OFFSETS ])

  def can_place_structure(self, location, desired_height):
    resources = [ g.position for g in (self.vespene_geyser + self.mineral_field) ]
    ramps = self.game_info.map_ramps
    return all(self.in_placement_grid(pos) and abs(self.get_terrain_height(pos) - desired_height) < 0.5 and all(r.is_further_than(1.0, pos) for r in resources) and all(all(point.is_further_than(1.0, pos) for point in r.points) for r in ramps) for pos in [ offset + location for offset in _3X3_OFFSETS ])

  def initialize_plans(self, base):
    print("Creating building plan for base")

    plan = ProtossBasePlan()
    base_terrain_height = self.get_terrain_height(base.position)
    for mutate in mutators:
      for i in range(len(pylon_positions)):
        if all(self.can_place_pylon(mutate(pos) + base.position, base_terrain_height) for pos in pylon_positions[i]) and \
           all(self.can_place_structure(mutate(pos, 3) + base.position, base_terrain_height) for pos in structure_positions[i]):
          plan.pylon_positions += [ mutate(pos) + base.position for pos in pylon_positions[i]]
          plan.structure_positions += [ mutate(pos, 3) + base.position for pos in structure_positions[i]]

    return plan

  def get_available_positions(self, structure_type, near=None):
    for nex_tag in list(self.plans.keys()):
      if nex_tag not in [ nex.tag for nex in self.townhalls ]:
        del self.plans[nex_tag]
    for nex in self.townhalls:
      if nex.tag not in self.plans:
        self.plans[nex.tag] = self.initialize_plans(nex)
    if structure_type == UnitTypeId.PYLON:
      return self._get_pylon_positions()
    else:
      return self._get_non_pylon_positions(near)

  def _get_pylon_positions(self):
    base_locations = [ nex.position for nex in self.townhalls ]
    existing_pylons = [ pylon.position for pylon in self.structures(UnitTypeId.PYLON) ]
    acceptable_positions = [ p for p in list_flatten([ p.pylon_positions for p in self.plans.values() ]) if p not in existing_pylons ]

    random.shuffle(acceptable_positions)
    # Move god pylons to the front - minimizes POOR PLANNING issues, and gives all bases pylons
    for i in range(len(acceptable_positions)):
      if any(acceptable_positions[i] - base_location in god_pylons for base_location in base_locations):
        acceptable_positions.insert(0, acceptable_positions.pop(i))
    return [p for p in acceptable_positions if not self.structures.closer_than(1.0, p).exists]

  def _get_non_pylon_positions(self, near):
    acceptable_positions = self.plans[near.tag].structure_positions if near else list_flatten([ p.structure_positions for p in self.plans.values() ])
    return [ p for p in acceptable_positions if self.state.psionic_matrix.covers(p) and not self.structures.closer_than(1.0, p).exists ]
