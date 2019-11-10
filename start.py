import itertools
import logging
import math
import random

import sc2
from sc2 import Race, Difficulty
from sc2.player import Bot, Computer
from sc2.data import AIBuild

from maps import all_maps
from protoss_reactive import build as build_protoss
from zerg_experimental import build as build_zerg

# protoss_bot = build_protoss()
zerg_bot = build_zerg()

def main():
  sc2.run_game(sc2.maps.get(random.choice(all_maps)), [
    Bot(Race.Zerg, zerg_bot),
    Computer(Race.Zerg, Difficulty.VeryHard, AIBuild.Macro) # Macro, Power, Rush, Timing, Air, (RandomBuild)
  ], realtime=False)

if __name__ == '__main__':
  main()
