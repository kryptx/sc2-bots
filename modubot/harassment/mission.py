import enum

from sc2.constants import UnitTypeId, AbilityId
from modubot.common import Urgency, BaseStructures, BuildRequest, median_position

class HarassmentMissionStatus(enum.IntFlag):
  PENDING = 0,
  BUILDING = 1,
  ATTACKING = 2,
  COMPLETE = 3

class HarassmentMission():
  def __init__(self, bot, when=lambda: True, harass_with=dict()):
    self.bot = bot
    self.condition = when
    self.desired_army = harass_with
    self.status = HarassmentMissionStatus.PENDING
    self.active_attackers = set()
    self.order_given = set()

  def __getattr__(self, name):
    return getattr(self.bot, name)

  async def on_step(self):
    if self.status == HarassmentMissionStatus.PENDING:
      if self.condition():
        self.bot.log.info("Harassment Mission Status: Building")
        self.status = HarassmentMissionStatus.BUILDING

    if self.status == HarassmentMissionStatus.BUILDING:
      requests = []
      units_ready = True
      for unit_type in self.desired_army.keys():
        if self.units(unit_type).amount < self.desired_army[unit_type]:
          needed_quantity = self.desired_army[unit_type] - (self.units(unit_type).amount + self.already_pending(unit_type))
          if needed_quantity > 0:
            requests.append(BuildRequest(unit_type, Urgency.VERYHIGH))
        if self.unallocated(unit_type, Urgency.VERYHIGH).amount < self.desired_army[unit_type]:
          units_ready = False
      if units_ready:
        for unit_type in self.desired_army.keys():
          aggressors = { u.tag for u in self.unallocated(unit_type, Urgency.VERYHIGH) }
          self.deallocate(aggressors)
          self.active_attackers = self.active_attackers.union(aggressors)
        self.bot.log.info("Harassment Mission Status: Attacking")
        self.status = HarassmentMissionStatus.ATTACKING
      else:
        return requests

    if self.status == HarassmentMissionStatus.ATTACKING:
      tagged_units = self.units.tags_in(self.active_attackers)
      if tagged_units.empty:
        self.active_attackers = set()
        self.bot.log.info("Harassment Mission Status: Complete")
        self.status = HarassmentMissionStatus.COMPLETE
      else:
        self.active_attackers = { u.tag for u in tagged_units }
        order_required = tagged_units.filter(lambda u: u.tag not in self.order_given)
        if order_required.empty:
          return  # don't need to return requests at this point; building happens only when status is building

        staging_area = median_position([ u.position for u in order_required ])
        if order_required.further_than(10, staging_area).exists:
          for aggressor in order_required:
            self.do(aggressor.move(staging_area))
          return

        centroid = self.enemy_structures.center
        def distance_to_enemy_base(position):
          return position.distance_to(centroid)

        enemy_base = min(self.enemy_start_locations, key=distance_to_enemy_base)
        enemy_minerals = self.mineral_field.closer_than(10, enemy_base)

        if enemy_minerals.exists:
          target = enemy_minerals.random.position.towards(enemy_base, 2)
          for aggressor in order_required:
            self.do(aggressor.move(target))
            self.order_given.add(aggressor.tag)
