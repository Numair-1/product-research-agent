"""Resume after a throttle with an extra cooldown, using exactly the same grader."""
import time

import run


class CooledModel(run.PacedModel):
    def decide(self, *args):
        # Leave more room for prompts containing page text. The base class still
        # honors 429 Retry-After and its one-retry cap. No provider call is faked.
        time.sleep(max(0, self.last_request + 20 - time.monotonic()))
        return super().decide(*args)


if __name__ == '__main__':
    time.sleep(65)
    run.PacedModel = CooledModel
    run.main()
