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

def gas_urgency(bot):
  def compute_gas_priority(geysers):
    if bot.already_pending(UnitTypeId.EXTRACTOR):
      return Urgency.NONE
    elif bot.structures(UnitTypeId.EXTRACTOR).amount < bot.townhalls.amount / 2:
      return Urgency.HIGH
    else:
      return Urgency.VERYLOW
  return compute_gas_priority

def worker_urgency(bot):
  def compute_urgency():
    urgency = Urgency.VERYHIGH

    if bot.shared.optimism < 1:
      urgency -= 6
    elif bot.shared.optimism < 0.95:
      urgency -= 7
    elif bot.shared.optimism < 0.9:
      urgency -= 8
    elif bot.shared.optimism < 0.85:
      urgency -= 9
    elif bot.shared.optimism < 0.8:
      urgency -= 10
    # elif bot.shared.optimism < 0.75:
    #   urgency -= 8
    # elif bot.shared.optimism < 0.7:
    #   urgency -= 9

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
      SupplyBufferer(bot, compute_buffer=lambda bot: 2 + bot.townhalls.amount * 4),
      MacroManager(bot, gas_urgency=gas_urgency(bot), worker_urgency=worker_urgency(bot), fast_expand=True),
      ScoutManager(bot,
        missions=[
          FindBasesMission(bot, unit_priority=[ UnitTypeId.OVERLORD ], start_when=lambda: True),
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
            [ UpgradeId.ZERGLINGMOVEMENTSPEED ]
          ],
          Urgency.MEDIUM: [
            [ UpgradeId.GLIALRECONSTITUTION ],
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
