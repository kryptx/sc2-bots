from sc2.constants import UnitTypeId
from sc2.position import Point2
from sc2.units import Units

from modubot.common import BaseStructures
from modubot.scouting.mission import ScoutingMission, identity

class WatchEnemyArmyMission(ScoutingMission):
  def __init__(self, bot, unit_priority=[], retreat_while=lambda scout: False):
    super().__init__(bot, unit_priority, retreat_while)
    self.static_targets = False

  def prerequisite(self):
    return self.shared.enemy_is_rushing != None

  def generate_targets(self):
    # what combat units do we know about?
    is_combat_unit = lambda e: (e.type_id not in (UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV))
    known_enemy_units = Units(self.shared.known_enemy_units.values(), self.bot).filter(is_combat_unit)
    seen_enemy_units = self.enemy_units.filter(is_combat_unit)

    if seen_enemy_units.amount > known_enemy_units.amount / 5:
      self.is_lost = False

    if known_enemy_units.exists:
      enemies_center = known_enemy_units.center
      if self.unit:
        scout = self.unit
        if scout.position.distance_to(enemies_center) < 5 and self.enemy_units.closer_than(10, scout.position).empty:
          self.is_lost = True
        if self.is_lost:
          # we got some bad intel, boys
          enemy_bases = self.enemy_structures(BaseStructures)
          if enemy_bases.exists:
            self.targets = [ enemy_bases.furthest_to(scout.position) ]
          else:
            # look man, I just wanna find some bad guys to spy on, why all the hassle
            self.targets = [ pos for pos in self.enemy_start_locations if self.state.visibility[Point2([ int(pos.x), int(pos.y) ])] == 0 ]
        else:
          towards_danger = enemies_center - scout.position
          to_the_side = Point2([ towards_danger.y, -towards_danger.x ]) if int(self.time / 30) % 2 == 0 else Point2([ -towards_danger.y, towards_danger.x ])
          self.targets = [ enemies_center.towards(enemies_center + to_the_side, 4) ]
      else:
        self.targets = [ enemies_center ]
    else:
      self.targets = [ b.position for b in self.enemy_structures ]
