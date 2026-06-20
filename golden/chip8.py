"""A complete CHIP-8 interpreter: the M1 golden model.

This proves the workload (a CHIP-8 program, eventually a raycaster) runs and
renders correctly in plain Python with zero OpenTTD involvement. The same display
buffer that this class draws into maps 1:1 onto the signal framebuffer on the
train substrate, so getting this exactly right pins down the reference behaviour
the hardware build has to match.

Memory map
----------
0x000-0x04F  reserved (interpreter scratch on real hardware)
0x050-0x09F  the 4x5 hex font (16 glyphs, 5 bytes each)
0x200        program load address, where PC starts

Quirks
------
CHIP-8 has a handful of behaviours that differ between historical
implementations. Programs were written against one set of choices, so we expose
them as flags and default to the classic COSMAC VIP behaviour, which is what the
Timendus test suite checks against:

  vf_reset      8XY1/2/3 (OR/AND/XOR) clear VF as a side effect.
  mem_i_inc     FX55/FX65 increment I by X+1 after the load/store.
  shift_use_vy  8XY6/8XYE shift VY into VX (not VX in place).
  jump_quirk    BNNN uses V0 (classic), not BXNN with VX.
  clip          DXYN clips sprites at the screen edges (no wrap of drawn pixels).
  display_wait  DXYN blocks until the next 60Hz tick (VIP draw timing).

display_wait is modelled as a flag the caller can honour when pacing the machine.
The interpreter records on each DXYN that a draw happened (`draw_pending`) so a
front end can sync drawing to the timer tick. The instruction itself always draws
because a headless test does not have a real vblank to wait on.
"""

from __future__ import annotations

import numpy as np

# screen geometry, fixed by the CHIP-8 spec.
SCREEN_W = 64
SCREEN_H = 32

FONT_ADDR = 0x50
PROGRAM_ADDR = 0x200
MEMORY_SIZE = 4096

# the standard 4x5 hex font, 16 glyphs of 5 bytes. high nibble of each byte is the
# drawn row, low nibble is unused. this is the conventional layout every CHIP-8
# emulator ships, loaded at 0x50.
FONT = [
    0xF0, 0x90, 0x90, 0x90, 0xF0,  # 0
    0x20, 0x60, 0x20, 0x20, 0x70,  # 1
    0xF0, 0x10, 0xF0, 0x80, 0xF0,  # 2
    0xF0, 0x10, 0xF0, 0x10, 0xF0,  # 3
    0x90, 0x90, 0xF0, 0x10, 0x10,  # 4
    0xF0, 0x80, 0xF0, 0x10, 0xF0,  # 5
    0xF0, 0x80, 0xF0, 0x90, 0xF0,  # 6
    0xF0, 0x10, 0x20, 0x40, 0x40,  # 7
    0xF0, 0x90, 0xF0, 0x90, 0xF0,  # 8
    0xF0, 0x90, 0xF0, 0x10, 0xF0,  # 9
    0xF0, 0x90, 0xF0, 0x90, 0x90,  # A
    0xE0, 0x90, 0xE0, 0x90, 0xE0,  # B
    0xF0, 0x80, 0x80, 0x80, 0xF0,  # C
    0xE0, 0x90, 0x90, 0x90, 0xE0,  # D
    0xF0, 0x80, 0xF0, 0x80, 0xF0,  # E
    0xF0, 0x80, 0xF0, 0x80, 0x80,  # F
]


class Chip8:
    """A CHIP-8 virtual machine.

    State is plain attributes so tests can poke and read it directly. `step`
    executes one instruction, `tick_timers` decrements the 60Hz timers, and
    `run` is a convenience loop.
    """

    def __init__(
        self,
        *,
        seed: int = 0,
        vf_reset: bool = True,
        mem_i_inc: bool = True,
        shift_use_vy: bool = True,
        jump_quirk: bool = False,
        clip: bool = True,
        display_wait: bool = True,
    ) -> None:
        # quirk flags, classic CHIP-8 defaults.
        self.vf_reset = vf_reset
        self.mem_i_inc = mem_i_inc
        self.shift_use_vy = shift_use_vy
        self.jump_quirk = jump_quirk
        self.clip = clip
        self.display_wait = display_wait

        # seedable RNG so CXNN is deterministic in tests.
        self._rng = np.random.RandomState(seed)

        self.reset()

    # --- lifecycle ----------------------------------------------------------

    def reset(self) -> None:
        """Clear all state and reload the font. Does not clear a loaded ROM,
        call load_rom again if you need the program back."""
        self.memory = bytearray(MEMORY_SIZE)
        self.V = bytearray(16)            # V0..VF, 8-bit registers.
        self.I = 0                        # index register, 16-bit.
        self.pc = PROGRAM_ADDR
        self.stack: list[int] = []
        self.delay_timer = 0
        self.sound_timer = 0
        self.display = np.zeros((SCREEN_H, SCREEN_W), dtype=np.uint8)
        self.keypad = [0] * 16            # 16-key hex keypad, 1 == pressed.
        self.draw_pending = False         # set by DXYN, cleared by the caller.
        self.waiting_for_key = None       # register index while blocked on FX0A.
        self.halted = False               # set if we hit an unknown opcode.

        # load the font at 0x50.
        for i, b in enumerate(FONT):
            self.memory[FONT_ADDR + i] = b

    def load_rom(self, data: bytes) -> None:
        """Load a program at 0x200 and reset PC there."""
        if PROGRAM_ADDR + len(data) > MEMORY_SIZE:
            raise ValueError("ROM too large for 4K memory")
        self.memory[PROGRAM_ADDR:PROGRAM_ADDR + len(data)] = data
        self.pc = PROGRAM_ADDR

    def load_rom_file(self, path: str) -> None:
        with open(path, "rb") as f:
            self.load_rom(f.read())

    def seed(self, value: int) -> None:
        """Reseed the RNG used by CXNN."""
        self._rng = np.random.RandomState(value)

    # --- timers -------------------------------------------------------------

    def tick_timers(self) -> None:
        """Decrement the delay and sound timers, called at 60Hz."""
        if self.delay_timer > 0:
            self.delay_timer -= 1
        if self.sound_timer > 0:
            self.sound_timer -= 1

    # --- execution ----------------------------------------------------------

    def step(self) -> None:
        """Fetch, decode, and execute one instruction."""
        if self.halted:
            return

        # FX0A blocks the machine until a key is pressed. while blocked we do not
        # advance PC, we just watch the keypad.
        if self.waiting_for_key is not None:
            for k in range(16):
                if self.keypad[k]:
                    self.V[self.waiting_for_key] = k
                    self.waiting_for_key = None
                    break
            return

        # a PC sitting at the top of memory would make the low-byte fetch read
        # memory[0x1000], one past the end of the 4K array, and raise IndexError.
        # halt gracefully like every other bad-state path instead.
        if self.pc + 1 >= MEMORY_SIZE:
            self.halted = True
            return

        opcode = (self.memory[self.pc] << 8) | self.memory[self.pc + 1]
        self.pc = (self.pc + 2) & 0xFFF

        self._execute(opcode)

    def run(self, cycles: int) -> None:
        """Run a fixed number of instructions. Timer ticks are the caller's job,
        see viewer.run_rom for a paced loop."""
        for _ in range(cycles):
            if self.halted:
                break
            self.step()

    def _execute(self, opcode: int) -> None:
        # standard nibble decode.
        nnn = opcode & 0x0FFF
        nn = opcode & 0x00FF
        n = opcode & 0x000F
        x = (opcode & 0x0F00) >> 8
        y = (opcode & 0x00F0) >> 4
        head = (opcode & 0xF000) >> 12

        if head == 0x0:
            if opcode == 0x00E0:          # 00E0 clear screen.
                self.display[:] = 0
                self.draw_pending = True
            elif opcode == 0x00EE:        # 00EE return from subroutine.
                # a return with no matching call would pop an empty stack and
                # raise IndexError. halt gracefully like every other bad state.
                if not self.stack:
                    self.halted = True
                    return
                self.pc = self.stack.pop()
            else:
                # 0NNN machine call. unused by modern ROMs, treat as no-op.
                pass

        elif head == 0x1:                 # 1NNN jump.
            self.pc = nnn

        elif head == 0x2:                 # 2NNN call subroutine.
            self.stack.append(self.pc)
            self.pc = nnn

        elif head == 0x3:                 # 3XNN skip if VX == NN.
            if self.V[x] == nn:
                self.pc = (self.pc + 2) & 0xFFF

        elif head == 0x4:                 # 4XNN skip if VX != NN.
            if self.V[x] != nn:
                self.pc = (self.pc + 2) & 0xFFF

        elif head == 0x5:                 # 5XY0 skip if VX == VY.
            if n != 0x0:
                self.halted = True
            elif self.V[x] == self.V[y]:
                self.pc = (self.pc + 2) & 0xFFF

        elif head == 0x6:                 # 6XNN set VX = NN.
            self.V[x] = nn

        elif head == 0x7:                 # 7XNN add NN to VX (no carry).
            self.V[x] = (self.V[x] + nn) & 0xFF

        elif head == 0x8:
            self._arith(x, y, n)

        elif head == 0x9:                 # 9XY0 skip if VX != VY.
            if n != 0x0:
                self.halted = True
            elif self.V[x] != self.V[y]:
                self.pc = (self.pc + 2) & 0xFFF

        elif head == 0xA:                 # ANNN set I = NNN.
            self.I = nnn

        elif head == 0xB:                 # BNNN jump with offset.
            if self.jump_quirk:
                # BXNN: offset by VX. used by some SUPER-CHIP programs.
                self.pc = (nnn + self.V[x]) & 0xFFF
            else:
                self.pc = (nnn + self.V[0]) & 0xFFF

        elif head == 0xC:                 # CXNN set VX = rand() & NN.
            self.V[x] = int(self._rng.randint(0, 256)) & nn

        elif head == 0xD:                 # DXYN draw sprite.
            self._draw(x, y, n)

        elif head == 0xE:
            if nn == 0x9E:                # EX9E skip if key VX pressed.
                if self.keypad[self.V[x] & 0xF]:
                    self.pc = (self.pc + 2) & 0xFFF
            elif nn == 0xA1:              # EXA1 skip if key VX not pressed.
                if not self.keypad[self.V[x] & 0xF]:
                    self.pc = (self.pc + 2) & 0xFFF
            else:
                self.halted = True

        elif head == 0xF:
            self._misc(x, nn)

        else:
            # unknown opcode, halt rather than silently misbehave.
            self.halted = True

    def _arith(self, x: int, y: int, n: int) -> None:
        """The 8XY_ ALU ops. VF is written AFTER the result, which matters when
        x == 0xF, the flag write wins."""
        vx = self.V[x]
        vy = self.V[y]

        if n == 0x0:                      # 8XY0 set VX = VY.
            self.V[x] = vy

        elif n == 0x1:                    # 8XY1 VX |= VY.
            self.V[x] = vx | vy
            if self.vf_reset:
                self.V[0xF] = 0

        elif n == 0x2:                    # 8XY2 VX &= VY.
            self.V[x] = vx & vy
            if self.vf_reset:
                self.V[0xF] = 0

        elif n == 0x3:                    # 8XY3 VX ^= VY.
            self.V[x] = vx ^ vy
            if self.vf_reset:
                self.V[0xF] = 0

        elif n == 0x4:                    # 8XY4 VX += VY, VF = carry.
            total = vx + vy
            self.V[x] = total & 0xFF
            self.V[0xF] = 1 if total > 0xFF else 0

        elif n == 0x5:                    # 8XY5 VX -= VY, VF = NOT borrow.
            self.V[x] = (vx - vy) & 0xFF
            self.V[0xF] = 1 if vx >= vy else 0

        elif n == 0x6:                    # 8XY6 shift right, VF = lost bit.
            src = vy if self.shift_use_vy else vx
            self.V[x] = (src >> 1) & 0xFF
            self.V[0xF] = src & 0x1

        elif n == 0x7:                    # 8XY7 VX = VY - VX, VF = NOT borrow.
            self.V[x] = (vy - vx) & 0xFF
            self.V[0xF] = 1 if vy >= vx else 0

        elif n == 0xE:                    # 8XYE shift left, VF = lost bit.
            src = vy if self.shift_use_vy else vx
            self.V[x] = (src << 1) & 0xFF
            self.V[0xF] = (src >> 7) & 0x1

        else:
            # 8XY8..8XYD are not assigned, halt.
            self.halted = True

    def _draw(self, x: int, y: int, n: int) -> None:
        """DXYN: XOR an N-row sprite at (VX, VY). VF is set if any on pixel got
        turned off (collision). The start coordinate wraps modulo the screen,
        but with clip on, the body of the sprite is clipped at the right and
        bottom edges rather than wrapping around."""
        start_x = self.V[x] % SCREEN_W
        start_y = self.V[y] % SCREEN_H
        self.V[0xF] = 0

        for row in range(n):
            py = start_y + row
            if self.clip and py >= SCREEN_H:
                break
            py %= SCREEN_H
            sprite_byte = self.memory[(self.I + row) & 0xFFF]
            for col in range(8):
                if not (sprite_byte & (0x80 >> col)):
                    continue
                px = start_x + col
                if self.clip and px >= SCREEN_W:
                    continue
                px %= SCREEN_W
                if self.display[py, px]:
                    self.V[0xF] = 1
                self.display[py, px] ^= 1

        self.draw_pending = True

    def _misc(self, x: int, nn: int) -> None:
        """The FX__ family: timers, key wait, index math, font, BCD, save/load."""
        if nn == 0x07:                    # FX07 VX = delay timer.
            self.V[x] = self.delay_timer

        elif nn == 0x0A:                  # FX0A wait for key, store in VX.
            # check if a key is already down. otherwise enter the blocking state
            # that step() polls each cycle.
            pressed = next((k for k in range(16) if self.keypad[k]), None)
            if pressed is not None:
                self.V[x] = pressed
            else:
                self.waiting_for_key = x

        elif nn == 0x15:                  # FX15 delay timer = VX.
            self.delay_timer = self.V[x]

        elif nn == 0x18:                  # FX18 sound timer = VX.
            self.sound_timer = self.V[x]

        elif nn == 0x1E:                  # FX1E I += VX.
            self.I = (self.I + self.V[x]) & 0xFFF

        elif nn == 0x29:                  # FX29 I = font address of digit VX.
            self.I = (FONT_ADDR + (self.V[x] & 0xF) * 5) & 0xFFF

        elif nn == 0x33:                  # FX33 store BCD of VX at I, I+1, I+2.
            val = self.V[x]
            self.memory[self.I & 0xFFF] = val // 100
            self.memory[(self.I + 1) & 0xFFF] = (val // 10) % 10
            self.memory[(self.I + 2) & 0xFFF] = val % 10

        elif nn == 0x55:                  # FX55 store V0..VX to memory at I.
            for i in range(x + 1):
                self.memory[(self.I + i) & 0xFFF] = self.V[i]
            if self.mem_i_inc:
                self.I = (self.I + x + 1) & 0xFFF

        elif nn == 0x65:                  # FX65 load V0..VX from memory at I.
            for i in range(x + 1):
                self.V[i] = self.memory[(self.I + i) & 0xFFF]
            if self.mem_i_inc:
                self.I = (self.I + x + 1) & 0xFFF

        else:
            # unknown FX encoding, halt rather than silently misbehave.
            self.halted = True

    # --- input helpers ------------------------------------------------------

    def key_down(self, key: int) -> None:
        self.keypad[key & 0xF] = 1

    def key_up(self, key: int) -> None:
        self.keypad[key & 0xF] = 0
