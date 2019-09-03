### BASE ADVISOR CLASS ###

class Advisor():
  def __init__(self, manager):
    self.manager = manager

  async def on_upgrade_complete(self, upgrade):
    return

  def tick(self):
    return []
