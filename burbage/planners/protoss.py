import random

from sc2.position import Point2
from sc2.constants import UnitTypeId
from burbage.common import BasePlanner, list_flatten

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

# PYLON POSITIONS ARE BOTTOM LEFT CORNER
pylon_positions = [
  # RED
  [ Point2([ 5, 4 ]),
    Point2([ 8, 1 ]), ],
  # YELLOW
  [ Point2([ 5, 4 ]),
    Point2([ 2, 7 ]), ],
  # GREEN
  [ Point2([ 10, 1 ]),
    Point2([ 12, 1 ]) ],
  # AQUA
  [ Point2([ 2, 9 ]),
    Point2([ 2, 11 ]) ],
  # BLUE
  [ Point2([ 9, 11 ]),
    Point2([ 12, 8 ])
  ]
]

# STRUCTURE POSITIONS ARE CENTERED
structure_positions = [
  # RED
  [ Point2([ 6, 2 ]),
    Point2([ 9, 4 ]) ],
  # YELLOW
  [ Point2([ 3, 5 ]),
    Point2([ 5, 8 ]) ],
  # GREEN
  [ Point2([ 12, 4 ]) ],
  # AQUA
  [ Point2([ 5, 11 ]) ],
  # BLUE
  [ Point2([ 10, 9 ]) ],
]

def identity(point, size=2):
  return point
def flip_x(point, size=2):
  return Point2([ -point.x + size - 3, point.y ])
def flip_y(point, size=2):
  return Point2([ point.x, -point.y + size - 3 ])
def flip_both(point, size=2):
  return Point2([ -point.x + size - 3, -point.y + size - 3 ])

mutators = [ identity, flip_x, flip_y, flip_both ]
god_pylons = [ mutate(Point2([ 5, 4 ])) for mutate in mutators ]

class ProtossBasePlan():
  def __init__(self):
    self.pylon_positions = []
    self.structure_positions = []

class ProtossBasePlanner(BasePlanner):
  def __init__(self, manager):
    super().__init__(manager)
    return

  def can_place_pylon(self, location):
    resources = [ g.position for g in (self.manager.vespene_geyser + self.manager.mineral_field) ]
    return all(self.manager.in_placement_grid(pos) and all(r.is_further_than(1.0, pos) for r in resources) for pos in [ offset + location for offset in _2X2_OFFSETS ])

  def can_place_structure(self, location):
    resources = [ g.position for g in (self.manager.vespene_geyser + self.manager.mineral_field) ]
    return all(self.manager.in_placement_grid(pos) and all(r.is_further_than(1.0, pos) for r in resources) for pos in [ offset + location for offset in _3X3_OFFSETS ])

  def initialize_plans(self, base):
    print("Creating building plan for base")

    plan = ProtossBasePlan()

    for mutate in mutators:
      for i in range(len(pylon_positions)):
        if all(self.can_place_pylon(mutate(pos) + base.position) for pos in pylon_positions[i]) and \
           all(self.can_place_structure(mutate(pos, 3) + base.position) for pos in structure_positions[i]):
          plan.pylon_positions += [ mutate(pos) + base.position for pos in pylon_positions[i]]
          plan.structure_positions += [ mutate(pos, 3) + base.position for pos in structure_positions[i]]

    return plan

  def get_available_positions(self, structure_type):
    for nex_tag in list(self.plans.keys()):
      if nex_tag not in [ nex.tag for nex in self.manager.townhalls ]:
        del self.plans[nex_tag]
    for nex in self.manager.townhalls:
      if nex.tag not in self.plans:
        self.plans[nex.tag] = self.initialize_plans(nex)
    if structure_type == UnitTypeId.PYLON:
      return self._get_pylon_positions()
    else:
      return self._get_non_pylon_positions()

  def _get_pylon_positions(self):
    base_locations = [ nex.position for nex in self.manager.townhalls ]
    existing_pylons = [ pylon.position for pylon in self.manager.structures(UnitTypeId.PYLON) ]
    acceptable_positions = [ p for p in list_flatten([ p.pylon_positions for p in self.plans.values() ]) if p not in existing_pylons ]

    random.shuffle(acceptable_positions)
    # Move god pylons to the front - minimizes POOR PLANNING issues
    for i in range(len(acceptable_positions)):
      if any(acceptable_positions[i] - base_location in god_pylons for base_location in base_locations):
        acceptable_positions.insert(0, acceptable_positions.pop(i))
    return [p for p in acceptable_positions if not self.manager.structures.closer_than(1.0, p).exists]

  def _get_non_pylon_positions(self):
    acceptable_positions = list_flatten([ p.structure_positions for p in self.plans.values() ])
    return [ p for p in acceptable_positions if self.manager.state.psionic_matrix.covers(p) and not self.manager.structures.closer_than(1.0, p).exists ]
