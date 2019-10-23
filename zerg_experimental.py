from sc2.constants import UnitTypeId, BuffId, UpgradeId

from modubot.bot import ModuBot
from modubot.common import Urgency
from modubot.modules import *
from modubot.scouting import *
from modubot.objectives.objective import ObjectiveStatus

def army_priority(bot):
  def unit_amount(unit_id):
    return bot.units(unit_id).amount

  def calculate_priorities():
    priority = [ UnitTypeId.ROACH, UnitTypeId.ZERGLING ]
    if bot.townhalls.amount > 1:
      priority = sorted([ UnitTypeId.HYDRALISK, UnitTypeId.ROACH ], key=unit_amount)
    bot.log.info(f"Returning unit priority {priority}")
    return priority

  return calculate_priorities

def build():
  bot = ModuBot()

  bot.modules = [
      GameStateTracker(bot),
      OptimismChatter(bot),
      SpectatorCamera(bot),
      WorkerDistributor(bot),
      CreepSpreader(bot),
      LarvaInjector(bot),
      AttackBases(bot),
      DefendBases(bot),
      RallyPointer(bot),
      SupplyBufferer(bot),
      MacroManager(bot, fast_expand=True),
      ScoutManager(bot,
        missions=[
          FindBasesMission(bot, unit_priority=[ UnitTypeId.ZERGLING, UnitTypeId.DRONE ], start_when=lambda: bot.townhalls.amount > 1),
          DetectCheeseMission(bot, unit_priority=[ UnitTypeId.ZERGLING, UnitTypeId.DRONE ]),
          ExpansionHuntMission(bot, unit_priority=[ UnitTypeId.ZERGLING, UnitTypeId.ROACH ]),
          ExpansionHuntMission(bot, unit_priority=[ UnitTypeId.OVERLORD ]),
          ExpansionHuntMission(bot, unit_priority=[ UnitTypeId.OVERLORD ]),
          WatchEnemyArmyMission(bot, unit_priority=[ UnitTypeId.ZERGLING ]),
          WatchEnemyArmyMission(bot, unit_priority=[ UnitTypeId.OVERLORD ]),
          SupportArmyMission(bot, unit_priority=[ UnitTypeId.OVERSEER ])
        ]),
      SimpleArmyBuilder(bot, get_priorities=army_priority(bot)),
      Upgrader(bot,
        upgrade_sets={
          Urgency.MEDIUM: [
            [ UpgradeId.GLIALRECONSTITUTION ]
          ],
          Urgency.MEDIUMLOW: [
            [ UpgradeId.ZERGMISSILEWEAPONSLEVEL1,
              UpgradeId.ZERGGROUNDARMORSLEVEL1,
              UpgradeId.ZERGMISSILEWEAPONSLEVEL2,
              UpgradeId.ZERGGROUNDARMORSLEVEL2,
              UpgradeId.ZERGMISSILEWEAPONSLEVEL3,
              UpgradeId.ZERGGROUNDARMORSLEVEL3 ],
            [ UpgradeId.OVERLORDSPEED ]
          ]
        }
      )
    ]

  return bot