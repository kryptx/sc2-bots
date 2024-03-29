import itertools
import random

from sc2.position import Point2
from sc2.constants import UnitTypeId
from modubot.common import BasePlanner, list_flatten

_SMALL_STRUCTURES = { UnitTypeId.SPINECRAWLER, UnitTypeId.SPORECRAWLER, UnitTypeId.SPIRE }

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

_TUMOR_OFFSETS = [
  Point2([ -10, 0 ]),
  Point2([ 10, 0 ]),
  Point2([ 5, 8 ]),
  Point2([ 5, -8]),
  Point2([ -5, 8 ]),
  Point2([ -5, -8 ])
]

crawler_positions = [
  # RED
  [ Point2([ 3.5, 9.5 ]) ],
  # YELLOW
  [ Point2([ 11.5, 1.5 ]),
    Point2([ 11.5, 3.5 ]),
    Point2([ 11.5, 5.5 ]), ],
  # CORAL BLUE
  [ ],
  # AQUA
  [ ],
  # PINK
  [ Point2([ 5.5, 10.5 ]),
    Point2([ 10.5, 9.5 ]) ],
  # ORANGE
  [ ],
  # UGLY GREEN
  [ ]
]

# STRUCTURE POSITIONS ARE CENTERED
structure_positions = [
  # RED
  [ Point2([ 3, 4 ]),
    Point2([ 3, 7 ])],
  # YELLOW
  [ ],
  # CORAL BLUE
  [ Point2([ 6, 5 ]),
    Point2([ 9, 5 ]) ],
  # AQUA
  [ Point2([ 6, 2 ]),
    Point2([ 9, 2 ]) ],
  # PINK
  [ Point2([ 8, 10 ]),
    Point2([ 9, 13 ]) ],
  # ORANGE
  [ Point2([ 3, 14 ]),
    Point2([ 6, 13 ]) ],
  # UGLY GREEN
  [ Point2([ 14, 5 ]),
    Point2([ 14, 2 ]) ]
]

def identity(point):
  return point
def rotate_right(point):
  return Point2([ point.y, -point.x ])
def rotate_left(point):
  return Point2([ -point.y, point.x ])
def flip_both(point):
  return Point2([ -point.x, -point.y ])

mutators = [ identity, rotate_left, rotate_right, flip_both ]

class ZergBasePlan():
  def __init__(self):
    self.small_positions = []
    self.large_positions = []

class ZergBasePlanner(BasePlanner):
  def __init__(self, bot):
    super().__init__(bot)
    return

  async def increase_buildable_area(self, workers):
    queens = self.bot.units(UnitTypeId.QUEEN).filter(lambda q: q.energy >= 25)
    if queens.exists and not self.already_pending(UnitTypeId.CREEPTUMOR):
      targets = self.planner.get_available_positions(UnitTypeId.CREEPTUMOR)
      for location in targets:
        can_build = await self.can_place_single(UnitTypeId.CREEPTUMOR, location)
        if can_build:
          self.log.warning("Force-built creep tumor.")
          return queens.closest_to(location).build(UnitTypeId.CREEPTUMOR, location)
      self.log.warning("Failed to force-build creep tumor.")
    else:
      self.log.info("Creep tumor already pending.")

  def can_place_small(self, location, desired_height):
    resources = [ g.position for g in (self.vespene_geyser + self.mineral_field) ]
    ramps = self.game_info.map_ramps
    return all(self.in_placement_grid(pos) and abs(self.get_terrain_height(pos) - desired_height) < 0.5 and all(r.is_further_than(1.0, pos) for r in resources) and all(all(point.is_further_than(1.0, pos) for point in r.points) for r in ramps) for pos in [ offset + location for offset in _2X2_OFFSETS ])

  def can_place_structure(self, location, desired_height):
    resources = [ g.position for g in (self.vespene_geyser + self.mineral_field) ]
    ramps = self.game_info.map_ramps
    return all(self.in_placement_grid(pos) and abs(self.get_terrain_height(pos) - desired_height) < 0.5 and all(r.is_further_than(1.0, pos) for r in resources) and all(all(point.is_further_than(1.0, pos) for point in r.points) for r in ramps) for pos in [ offset + location for offset in _3X3_OFFSETS ])

  def initialize_plans(self, base):
    self.log.info("Creating building plan for base")

    plan = ZergBasePlan()
    base_terrain_height = self.get_terrain_height(base.position)
    for mutate in mutators:
      for i in range(len(crawler_positions)):
        if all(self.can_place_small(mutate(pos) + base.position, base_terrain_height) for pos in crawler_positions[i]) and \
           all(self.can_place_structure(mutate(pos) + base.position, base_terrain_height) for pos in structure_positions[i]):
          plan.small_positions += [ mutate(pos) + base.position for pos in crawler_positions[i]]
          plan.large_positions += [ mutate(pos) + base.position for pos in structure_positions[i]]

    self.log.info(f"Returning crawler positions {plan.small_positions} and structure positions {plan.large_positions} ")
    return plan

  def get_available_positions(self, structure_type, near=None):
    if structure_type == UnitTypeId.HATCHERY:
      return []
    # common code handles juggling creep tumors between queens and tumors
    for base_tag in list(self.plans.keys()):
      if base_tag not in [ base.tag for base in self.townhalls ]:
        del self.plans[base_tag]
    for base in self.townhalls:
      if base.tag not in self.plans:
        self.plans[base.tag] = self.initialize_plans(base)
    if structure_type in _SMALL_STRUCTURES:
      return self._get_small_positions()
    else:
      return self._get_large_positions(near)

  def queen_tumor_position(self):
    bases = self.bot.townhalls
    tumors = self.bot.structures({ UnitTypeId.CREEPTUMOR })
    tumor_candidates = [
      p.position + offset
      for (p, offset) in itertools.product(bases, _TUMOR_OFFSETS)
      if self.bot.in_placement_grid(p.position + offset)
      and self.bot.has_creep(p.position + offset)
      and tumors.closer_than(2, p.position + offset).empty
    ]
    return tumor_candidates[0] if tumor_candidates else None

  def tumor_tumor_position(self, tumor):
    tp = tumor.position
    structures = self.bot.structures
    tumor_candidates = [
      tp + offset
      for offset in _TUMOR_OFFSETS
      if self.bot.in_placement_grid(tp + offset)
      and self.bot.has_creep(tp + offset)
      and structures.closer_than(5, tp + offset).empty
      and all(expansion.is_further_than(3, tp + offset) for expansion in self.bot.expansion_locations_dict.keys())
    ]
    return tumor_candidates[0] if tumor_candidates else None

  def _get_small_positions(self):
    existing_structures = [ structure.position for structure in self.structures(_SMALL_STRUCTURES) ]
    acceptable_positions = [
      p
      for p in list_flatten([ p.small_positions for p in self.plans.values() ])
      if p not in existing_structures
      and all(self.bot.has_creep(p + offset) for offset in _2X2_OFFSETS)
    ]
    random.shuffle(acceptable_positions)
    return [p for p in acceptable_positions if not self.structures.closer_than(1.0, p).exists]

  def _get_large_positions(self, near):
    acceptable_positions = self.plans[near.tag].large_positions if near else list_flatten([ p.large_positions for p in self.plans.values() ])
    return [
      p
      for p in acceptable_positions
      if all(self.bot.has_creep(p + offset) for offset in _3X3_OFFSETS)
      and not self.structures.closer_than(1.0, p).exists
    ]
