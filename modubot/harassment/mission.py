import enum

from sc2.constants import UnitTypeId, AbilityId
from modubot.common import Urgency, BaseStructures, BuildRequest

class HarassmentMissionStatus(enum.IntFlag):
  PENDING = 0,
  BUILDING = 1,
  ATTACKING = 2,
  COMPLETE = 3

class HarassmentMission():
  def __init__(self, bot, when=lambda: True, harass_with=dict(), urgency=Urgency.MEDIUMHIGH):
    self.bot = bot
    self.condition = when
    self.desired_army = harass_with
    self.status = HarassmentMissionStatus.PENDING
    self.active_attackers = set()
    self.urgency = urgency

  def __getattr__(self, name):
    return getattr(self.bot, name)

  async def on_step(self):
    requests = []
    if self.status == HarassmentMissionStatus.PENDING:
      if self.condition():
        self.status = HarassmentMissionStatus.BUILDING

    if self.status == HarassmentMissionStatus.BUILDING:
      units_ready = True
      for unit_type in self.desired_army.keys():
        if self.units(unit_type).amount < self.desired_army[unit_type]:
          needed_quantity = self.desired_army[unit_type] - (self.units(unit_type).amount + self.already_pending(unit_type))
          for i in range(int(needed_quantity / 2) + 1 if unit_type == UnitTypeId.ZERGLING else needed_quantity):
            requests.append(BuildRequest(unit_type, self.urgency))
        if self.unallocated(unit_type, Urgency.VERYHIGH).amount < self.desired_army[unit_type]:
          units_ready = False
      if units_ready:
        for unit_type in self.desired_army.keys():
          aggressors = { u.tag for u in self.unallocated(unit_type, Urgency.VERYHIGH) }
          self.deallocate(aggressors)
          self.active_attackers.union(aggressors)
          self.status = HarassmentMissionStatus.ATTACKING

    if self.status == HarassmentMissionStatus.ATTACKING:
      tagged_units = self.units.tags_in(self.active_attackers)
      if tagged_units.empty:
        self.active_attackers = set()
        self.status = HarassmentMissionStatus.COMPLETE
      else:
        self.active_attackers = { u.tag for u in tagged_units }
        aggressors = tagged_units.filter(lambda u: u.distance_to(self.shared.rally_point < 10))

        if aggressors.exists:
          enemy_bases = self.enemy_structures(BaseStructures)
          enemy_minerals = self.mineral_field.filter(lambda field: enemy_bases.closer_than(10, field.position).exists)

          if enemy_minerals.exists:
            for aggressor in aggressors:
              target = enemy_minerals.random.position
              base = enemy_bases.closest_to(target)
              aggressor.move(target.towards(base, 2))

    return requests
