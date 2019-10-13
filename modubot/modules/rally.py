from .module import BotModule

class RallyPointer(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    bot.shared.rally_point = None

  async def on_step(self, iteration):
    self.shared.rally_point = self.determine_rally_point()

  def determine_rally_point(self):
    if self.townhalls.empty or self.townhalls.amount == 1:
      return list(self.main_base_ramp.upper)[0]

    def distance_to_bases(ramp):
      return ramp.top_center.distance_to(self.bases_centroid().towards(self.game_info.map_center, 20))

    ramps = sorted(self.game_info.map_ramps, key=distance_to_bases)
    return list(ramps[0].upper)[0]
