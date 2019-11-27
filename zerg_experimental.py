from sc2.constants import UnitTypeId, BuffId, UpgradeId

from modubot.bot import ModuBot
from modubot.common import Urgency, BaseStructures
from modubot.modules import *
from modubot.scouting import *
from modubot.harassment.mission import HarassmentMission
from modubot.objectives.objective import ObjectiveStatus

def army_priority(bot):
  def unit_amount(unit_id):
    return bot.units(unit_id).amount

  def calculate_priorities():
    priority = []
    if bot.shared.optimism >= 0.6:
      # "happy" path. tech away.
      priority = [ UnitTypeId.ZERGLING ]
      if bot.structures(UnitTypeId.SPAWNINGPOOL).exists:
        priority.insert(0, UnitTypeId.ROACH)
        if bot.structures(UnitTypeId.ROACHWARREN).exists:
          priority.insert(0, UnitTypeId.HYDRALISK)
          if bot.structures(UnitTypeId.HYDRALISKDEN).exists:
            priority.sort(key=unit_amount)

      priority = [
        UnitTypeId.ROACH,
        UnitTypeId.ZERGLING
      ] if bot.townhalls.amount == 1 else sorted([
        UnitTypeId.HYDRALISK,
        UnitTypeId.ROACH,
        UnitTypeId.ZERGLING
      ], key=unit_amount)
    else:
      # stop making tech. jeez.
      priority = [ UnitTypeId.ZERGLING ]
      if bot.structures(UnitTypeId.ROACHWARREN).exists:
        priority.append(UnitTypeId.ROACH)
      if bot.structures(UnitTypeId.HYDRALISKDEN).exists:
        priority.append(UnitTypeId.HYDRALISK)

      priority.sort(key=unit_amount)

    bot.log.info(f"Returning unit priority {priority}")
    return priority

  return calculate_priorities

def gas_urgency(bot):
  def compute_gas_priority(geysers):
    if bot.already_pending(UnitTypeId.EXTRACTOR):
      return Urgency.NONE
    elif bot.structures(UnitTypeId.EXTRACTOR).amount < bot.townhalls.amount:
      return Urgency.HIGH
    else:
      return Urgency.VERYLOW
  return compute_gas_priority

def worker_urgency(bot):
  def compute_urgency():
    urgency = Urgency.VERYHIGH

    if bot.shared.optimism < 0.5:
      urgency = Urgency.MEDIUMLOW

    elif bot.shared.optimism < 0.625:
      urgency = Urgency.MEDIUM

    elif bot.shared.optimism < 0.75:
      urgency = Urgency.MEDIUMHIGH

    elif bot.shared.optimism < 0.875:
      urgency = Urgency.HIGH

    return urgency

  return compute_urgency

def build():
  bot = ModuBot(limits={
      UnitTypeId.ROACHWARREN: lambda: 1,
      UnitTypeId.EVOLUTIONCHAMBER: lambda: 2,
      UnitTypeId.SPAWNINGPOOL: lambda: 1,
      UnitTypeId.HYDRALISKDEN: lambda: 1,
      UnitTypeId.OVERSEER: lambda: 2
  })

  bot.modules = [
      GameStateTracker(bot),
      # OptimismChatter(bot),
      SpectatorCamera(bot),
      WorkerDistributor(bot),
      CreepSpreader(bot),
      LarvaInjector(bot),
      AttackBases(bot),
      DefendBases(bot),
      RallyPointer(bot),
      ZergMicro(bot),
      Harasser(bot, missions=[
        HarassmentMission(bot,
          when=lambda:
            bot.time < 300 and \
            bot.enemy_structures(BaseStructures).filter(lambda base: base.position not in bot.enemy_start_locations).exists,
          harass_with={ UnitTypeId.ZERGLING: 12 }
        )
      ]),
      SupplyBufferer(bot, compute_buffer=lambda bot: 2 + bot.townhalls.amount * 4),
      MacroManager(bot, gas_urgency=gas_urgency(bot), worker_urgency=worker_urgency(bot), fast_expand=True),
      ScoutManager(bot,
        missions=[
          FindBasesMission(bot, unit_priority=[ UnitTypeId.DRONE ], start_when=lambda: bot.time > 45),
          DetectCheeseMission(bot, unit_priority=[ UnitTypeId.ZERGLING, UnitTypeId.DRONE ]),
          ExpansionHuntMission(bot, unit_priority=[ UnitTypeId.ZERGLING, UnitTypeId.ROACH ]),
          ExpansionHuntMission(bot, unit_priority=[ UnitTypeId.OVERLORD ], start_when=lambda: True),
          ExpansionHuntMission(bot, unit_priority=[ UnitTypeId.OVERLORD ], start_when=lambda: True),
          WatchEnemyArmyMission(bot, unit_priority=[ UnitTypeId.ZERGLING ]),
          SupportArmyMission(bot, unit_priority=[ UnitTypeId.OVERSEER ])
        ]),
      SimpleArmyBuilder(bot, get_priorities=army_priority(bot)),
      Upgrader(bot,
        upgrade_sets={
          Urgency.MEDIUMHIGH: [
            [ UpgradeId.BURROW ],
            [ UpgradeId.ZERGLINGMOVEMENTSPEED ]
          ],
          Urgency.MEDIUM: [
            [ UpgradeId.EVOLVEGROOVEDSPINES,
              UpgradeId.EVOLVEMUSCULARAUGMENTS ],
            [ UpgradeId.ZERGMISSILEWEAPONSLEVEL1,
              UpgradeId.ZERGMISSILEWEAPONSLEVEL2,
              UpgradeId.ZERGMISSILEWEAPONSLEVEL3 ],
            [ UpgradeId.ZERGGROUNDARMORSLEVEL1,
              UpgradeId.ZERGGROUNDARMORSLEVEL2,
              UpgradeId.ZERGGROUNDARMORSLEVEL3 ],
          ],
          Urgency.MEDIUMLOW: [
            [ UpgradeId.OVERLORDSPEED ],
            [ UpgradeId.ZERGLINGATTACKSPEED ]
          ]
        }
      )
    ]

  return bot
