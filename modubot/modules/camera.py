import itertools
import sc2
from sc2.constants import UnitTypeId

from modubot.common import is_worker
from .module import BotModule

class SpectatorCamera(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    self.last_camera_move = 0

  async def on_step(self, iteration):
    if self.last_camera_move < self.time - 2:
      self.last_camera_move = self.time

      # if we're defending
      if self.shared.threats.amount > 1:
        await self._client.move_camera(self.shared.threats.closest_to(self.shared.threats.center))
        return

      # if we're attacking
      if self.shared.attackers and any(unit.position.is_closer_than(10, enemy) for (unit, enemy) in itertools.product(self.shared.attackers, self.shared.victims)):
        await self._client.move_camera(self.shared.attackers.closest_to(self.shared.victims.center))
        return

      # if we're building a new base
      if self.already_pending(UnitTypeId.NEXUS) > 0 and self.structures(UnitTypeId.NEXUS).not_ready.empty:
        await self._client.move_camera(self.shared.next_base_location)
        return

      # if we can see more than half their army
      enemy_army_size = len([ u for u in self.shared.known_enemy_units.values() if not is_worker(u) ])
      if self.enemy_units.amount > enemy_army_size / 2:
        await self._client.move_camera(self.enemy_units.closest_to(self.enemy_units.center))
        return

      if self.shared.scouts.exists:
        interesting_scouts = self.shared.scouts.filter(lambda scout:
          (self.enemy_units + self.enemy_structures).closer_than(8, scout.position).amount > 1)

        if interesting_scouts.exists:
          await self._client.move_camera(interesting_scouts.first.position)
          return

      def energy_amount(base):
        return base.energy

      await self._client.move_camera(
        self.shared.rally_point if self.shared.rally_point and self.units.closer_than(10, self.shared.rally_point).amount > 2
        else max(self.townhalls, key=energy_amount, default=self.start_location)
      )
