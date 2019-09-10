import random

import sc2
from sc2.constants import *
from sc2.position import Point2

class Urgency(enum.IntFlag):
  NONE = 0,       # don't do this
  VERYLOW = 1,    # Totally fine if it never happens
  LOW = 2,        # Whenever we have an excess
  MEDIUMLOW = 3,  # sometime relatively soon
  MEDIUM = 4,     # As a matter of course
  MEDIUMHIGH = 5, # soon
  HIGH = 6,       # maybe put some other things off
  VERYHIGH = 7,   # definitely put some other things off
  EXTREME = 8,    # absolutely do this right now
  LIFEORDEATH = 9 # if you can't do this, you might as well surrender

# PYLON POSITIONS ARE BOTTOM LEFT CORNER
pylon_positions = [
  # straight to the northeast
  [ Point2([ 7, 7 ]),
    Point2([ 7, 9 ]),
    Point2([ 9, 7 ]) ],
  [ Point2([ 2, 5 ]),
    Point2([ 2, 7 ]),
    Point2([ 2, 9 ]) ],
  [ Point2([ 2, 11 ]) ],
  [ Point2([ 5, 2 ]),
    Point2([ 7, 2 ]),
    Point2([ 9, 2 ]) ],
  [ Point2([ 11, 2 ]) ]
]

# STRUCTURE POSITIONS ARE CENTERED
structure_positions = [
  [ Point2([ 5, 5 ]),
    Point2([ 10, 10 ]) ],
  [ Point2([ 5, 8 ]), ],
  [ Point2([ 5, 11 ]), ],
  [ Point2([ 8, 5 ]), ],
  [ Point2([ 11, 5 ]), ]
]

class TrainingRequest():
  def __init__(self, unit_type, structure, urgency):
    self.unit_type = unit_type
    self.structure = structure
    self.urgency = urgency
    self.expense = unit_type

  async def fulfill(self, bot):
    return self.structure.train(self.unit_type)

class WarpInRequest():
  def __init__(self, unit_type, warpgate, location, urgency):
    self.unit_type = unit_type
    self.warpgate = warpgate
    self.location = location
    self.urgency = urgency
    self.expense = unit_type

  async def fulfill(self, bot):
    return self.warpgate.warp_in(self.unit_type, self.location)

class BasePlanner():
  def __init__(self, manager):
    self.manager = manager
    self.plans = dict()
    return

  def get_next_position(self, structure_type):
    raise NotImplementedError("You must override this function")

class ProtossBasePlan():
  def __init__(self):
    self.pylon_positions = []
    self.structure_positions = []

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
    def identity(point, size=2):
      return point
    def flip_x(point, size=2):
      return Point2([ -point.x + size - 3, point.y ])
    def flip_y(point, size=2):
      return Point2([ point.x, -point.y + size - 3 ])
    def flip_both(point, size=2):
      return Point2([ -point.x + size - 3, -point.y + size - 3 ])

    plan = ProtossBasePlan()

    mutators = [ identity, flip_x, flip_y, flip_both ]
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
    acceptable_positions = list_flatten([ p.pylon_positions for p in self.plans.values() ])
    random.shuffle(acceptable_positions)
    return [p for p in acceptable_positions if not self.manager.structures.closer_than(1.0, p).exists]

  def _get_non_pylon_positions(self):
    acceptable_positions = list_flatten([ p.structure_positions for p in self.plans.values() ])
    return [ p for p in acceptable_positions if self.manager.state.psionic_matrix.covers(p) and not self.manager.structures.closer_than(1.0, p).exists ]


class StructureRequest():
  def __init__(self, structure_type, planner, urgency=Urgency.LOW, force_target=None):
    self.planner = planner
    self.structure_type = structure_type
    self.urgency = urgency
    self.expense = structure_type
    self.force_target = force_target

  async def fulfill(self, bot):
    worker = bot.workers.filter(lambda w: w.is_idle or w.is_collecting)
    if not worker.exists:
      worker = bot.workers

    if not worker.exists:
      # womp womp
      return

    if self.force_target:
      return worker.closest_to(self.force_target).build(self.structure_type, self.force_target)

    targets = self.planner.get_available_positions(self.structure_type)
    for location in targets:
      can_build = await bot.can_place(self.structure_type, location)
      if can_build:
        return worker.closest_to(location).build(self.structure_type, location)

    print("FAILED TO BUILD STRUCTURE DUE TO POOR PLANNING")

class ResearchRequest():
  def __init__(self, ability, structure, urgency):
    self.ability = ability
    self.structure = structure
    self.urgency = urgency
    self.expense = ability

  async def fulfill(self, bot):
    return self.structure(self.ability)
    # return

class ExpansionRequest():
  def __init__(self, location, urgency):
    self.urgency = urgency
    self.expense = UnitTypeId.NEXUS
    self.location = location

  async def fulfill(self, bot):
    await bot.expand_now(location=self.location)
    return

def list_diff(first, second):
  second = set(second)
  return [item for item in first if item not in second]

def list_flatten(list_of_lists):
  return [item for sublist in list_of_lists for item in sublist]