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

  def get_available_positions(self, structure_type):
    raise NotImplementedError("You must override this function")

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