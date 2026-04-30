from pathlib import Path

class Store:
    def __init__(self, root_dir: Path = Path(".agentx")):
        self._root_dir = root_dir
        self._init_structure()
    
    @property
    def root_dir(self) -> Path:
        return self._root_dir
    
    @property
    def conversation_dir(self) -> Path:
        return self._root_dir / "conversation"
    
    @property
    def running_agent_store(self) -> Path:
        return self._root_dir / "running_agent"
    
    def _init_structure(self):
        self.root_dir.mkdir(exist_ok=True)
        self.conversation_dir.mkdir(exist_ok=True)
        self.running_agent_store.mkdir(exist_ok=True)
    
    def latest_history_file(self) -> Path | None:
        history_files = list(self.conversation_dir.glob("*.json"))
        if not history_files:
            return None
        history_files.sort(reverse=True)
        return history_files[0]
    
    def next_history_file(self) -> Path:
        # n_files = len(list(self.conversation_dir.glob("*.json")))
        latest_history_file = self.latest_history_file()
        if latest_history_file is None:
            latest_index = 0
        else:
            try:
                latest_index = int(latest_history_file.stem)
            except ValueError:
                latest_index = 0

        new_file = self.conversation_dir / f"{latest_index + 1:06d}.json"
        return new_file
    