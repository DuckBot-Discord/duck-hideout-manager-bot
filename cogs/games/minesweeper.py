from __future__ import annotations

from operator import eq
from typing import Self, Type
from itertools import chain, pairwise
from dataclasses import dataclass
from random import sample, randint

import discord
from discord.ext import commands
from discord.interactions import Interaction

from bot import HideoutManager
from utils import HideoutCog, HideoutContext, View


def num_as_emoji(num: int) -> str:
    if num == 10:
        return '\N{KEYCAP TEN}'
    return f"{num}\N{VARIATION SELECTOR-16}\N{COMBINING ENCLOSING KEYCAP}"


def num_as_letter(num: int) -> str:
    if 1 > num > 26:
        raise TypeError(f"You must provide a number between 1 and 26 (amount of letters in the alphabet.)")

    initial = ord('\N{REGIONAL INDICATOR SYMBOL LETTER A}')
    return chr(initial + num - 1)


class Theme:
    SELECTED = '\N{LARGE RED SQUARE}'
    CORNER_SYMBOL = '\N{ASTERISK}\N{VARIATION SELECTOR-16}\N{COMBINING ENCLOSING KEYCAP}'
    MINE = '\N{BOMB}'
    MINE_EXPLODED = '\N{COLLISION SYMBOL}'
    FLAG = '\N{TRIANGULAR FLAG ON POST}'
    FLAGGED_SQUARE = '\N{TRIANGULAR FLAG ON POST}'
    FIELD: str = NotImplemented
    FIELD_PRESSED: str = NotImplemented


class DarkTheme(Theme):
    FIELD = '\N{BLACK LARGE SQUARE}'
    FIELD_PRESSED = '\N{BLACK SQUARE BUTTON}'


class LightTheme(Theme):
    FIELD = '\N{WHITE LARGE SQUARE}'
    FIELD_PRESSED = '\N{WHITE SQUARE BUTTON}'


@dataclass
class MSField:
    x: int
    y: int
    revealed: bool = False
    flagged: bool = False
    mine: bool = False
    neighbours_amount: int = 0


class MSBoard:
    def __init__(self) -> None:
        self._board = [[MSField(x=x, y=y) for x in range(10)] for y in range(10)]
        for field in sample(list(chain.from_iterable(self._board)), randint(5, 15)):
            field.mine = True
            x, y = field.x, field.y
            targets: tuple[tuple[int, int], ...] = (
                (x - 1, y - 1),
                (x - 1, y),
                (x - 1, y + 1),
                (x, y - 1),
                (x, y + 1),
                (x + 1, y - 1),
                (x + 1, y),
                (x + 1, y + 1),
            )
            fields = filter(self.is_in_grid, targets)
            for x, y in fields:
                self._board[y][x].neighbours_amount += 1

        self.cursor_x: int | None = None
        self.cursor_y: int | None = None
        self.game_is_over: bool = False
        self.theme: Type[Theme] = LightTheme

    @property
    def current_field(self):
        if self.cursor_x is None or self.cursor_y is None:
            return None
        return self._board[self.cursor_y][self.cursor_x]

    def field_at(self, x: int, y: int):
        if not self.is_in_grid((x, y)):
            return None
        return self._board[y][x]

    @discord.utils.cached_property
    def size(self) -> tuple[int, int]:
        board = self._board
        if not board:
            return (0, 0)
        if not all(eq(first, second) for first, second in pairwise(map(len, board))):
            message = 'All rows of the board must be of the same size.'
            raise ValueError(message)
        return (len(board), len(board[0]))

    def toggle_theme(self):
        if self.theme is LightTheme:
            self.theme = DarkTheme
        else:
            self.theme = LightTheme

    def is_in_grid(self, position: tuple[int, int]):
        x, y = position
        if not self._board or not self._board[0]:
            return False
        return 0 <= x <= (len(self._board[0]) - 1) and 0 <= y <= (len(self._board) - 1)

    def draw(self):
        column: list[str] = [self.theme.CORNER_SYMBOL]
        for i in range(len(self._board[0])):
            if i == self.cursor_x:
                column.append(self.theme.SELECTED)
            else:
                column.append(num_as_emoji(i + 1))

        rows: list[list[str]] = [column]

        for index, row in enumerate(self._board):
            column: list[str] = []
            if index == self.cursor_y:
                column.append(self.theme.SELECTED)
            else:
                column.append(num_as_letter(index + 1))

            for field in row:
                match field:
                    case MSField(revealed=True, mine=True):
                        column.append(self.theme.MINE_EXPLODED)

                    case MSField(revealed=True):
                        if field.neighbours_amount:
                            column.append(num_as_emoji(field.neighbours_amount))
                        else:
                            column.append(self.theme.FIELD_PRESSED)

                    case MSField(flagged=True):
                        column.append(self.theme.FLAGGED_SQUARE)

                    case MSField(x=self.cursor_x, y=self.cursor_y):
                        column.append(self.theme.SELECTED)

                    case MSField(mine=True):
                        if self.game_is_over:
                            column.append(self.theme.MINE)
                        else:
                            column.append(self.theme.FIELD)

                    case MSField():
                        column.append(self.theme.FIELD)

            rows.append(column)

        return '\n'.join(''.join(col) for col in rows)

    def click(self, index: int):
        if self.cursor_x is not None:
            # both are clicked, reset
            self.cursor_y = None
            self.cursor_x = index

        elif self.cursor_y is not None:
            # only row is clicked, select a column
            self.cursor_x = index

        else:
            # nothing clicked, select a row
            self.cursor_y = index

    def reset_positions(self):
        self.cursor_x = None
        self.cursor_y = None

    def go_back(self):
        if self.cursor_x is not None:
            self.cursor_x = None
        elif self.cursor_y is not None:
            self.cursor_y = None

    def reveal_neighbours(self, field: MSField):
        if field.mine or field.revealed:
            return
        field.revealed = True
        if field.neighbours_amount:
            return
        x, y = field.x, field.y
        targets = (
            (x, y - 1),
            (x, y + 1),
            (x - 1, y),
            (x + 1, y),
        )
        for x, y in targets:
            neighbour = self.field_at(x, y)
            if not neighbour:
                continue
            self.reveal_neighbours(neighbour)

    def reveal_cell(self, field: MSField):
        if field.mine:
            field.revealed = True
            self.game_is_over = True
        else:
            self.reveal_neighbours(field)
            self.check_wins()

    def check_wins(self):
        def field_should_be_clicked(field: MSField):
            return not field.mine or not field.revealed

        to_be_clicked = filter(field_should_be_clicked, chain.from_iterable(self._board))

        if not to_be_clicked:
            self.game_is_over = True


class ColumnSelectorButton(discord.ui.Button['MSView']):
    def __init__(self, index: int, is_letter: bool):
        meth = num_as_letter if is_letter else num_as_emoji
        super().__init__(emoji=meth(index + 1), style=discord.ButtonStyle.blurple)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        if not self.view:
            return await interaction.response.send_message('Something borked...', ephemeral=True)
        await self.view.next(interaction, self.index)


class MSView(View):
    def __init__(self, *, bot: HideoutManager | None = None, owner: discord.abc.User):
        super().__init__(timeout=600, bot=bot)
        self.owner = owner
        self.board = MSBoard()

    async def start(self, ctx: HideoutContext):
        self.update_buttons()
        self.message = await ctx.send(self.board.draw(), view=self)

    def update_buttons(self):
        self.clear_items()

        if self.board.game_is_over:
            return self.stop()

        field = self.board.current_field
        if field:
            # Both are clicked, we need to choose an action to perform
            self.add_item(self.put_flag)
            self.add_item(self.reveal_button)
            self.add_item(self.go_back)

        elif self.board.cursor_y is not None:
            # letter is selected, we need to select a number
            for i in range(self.board.size[1]):
                self.add_item(ColumnSelectorButton(i, is_letter=False))
            self.add_item(self.go_back)

        else:
            # Neither selected, we need to select a letter
            for i in range(self.board.size[0]):
                self.add_item(ColumnSelectorButton(i, is_letter=True))

        self.add_item(self.toggle_theme)
        self.add_item(self.stop_game)

    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        await interaction.response.edit_message(content=self.board.draw(), view=self)

    async def next(self, interaction: discord.Interaction, index: int):
        self.board.click(index)
        await self.update_message(interaction)

    @discord.ui.button(emoji='\N{LEFTWARDS ARROW WITH HOOK}\N{VARIATION SELECTOR-16}', label='go back', row=2)
    async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        self.board.go_back()
        await self.update_message(interaction)

    @discord.ui.button(emoji=Theme.FLAG, label='Toggle Flag')
    async def put_flag(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        field = self.board.current_field
        if not field:
            return await self.update_message(interaction)
        if not field.revealed:
            field.flagged = not field.flagged
        self.board.reset_positions()
        await self.update_message(interaction)

    @discord.ui.button(emoji='\N{BLACK SQUARE FOR STOP}\N{VARIATION SELECTOR-16}', label='Click Square')
    async def reveal_button(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        field = self.board.current_field
        if not field:
            return await self.update_message(interaction)

        self.board.reveal_cell(field)
        self.board.reset_positions()
        if self.board.game_is_over:
            self.clear_items()
            self.stop()
        await self.update_message(interaction)

    @discord.ui.button(label='Toggle Theme', row=2, style=discord.ButtonStyle.green)
    async def toggle_theme(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        self.board.toggle_theme()
        await self.update_message(interaction)

    @discord.ui.button(label='Stop', row=2, style=discord.ButtonStyle.red)
    async def stop_game(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        self.board.game_is_over = True
        self.stop()
        await interaction.response.edit_message(content=f"Stopped by the user.\n{self.board.draw()}", view=None)

    async def on_timeout(self):
        try:
            self.board.game_is_over = True
            await self.message.edit(content=self.board.draw(), view=None)
        except discord.HTTPException:
            pass

    async def interaction_check(self, interaction: Interaction):
        if interaction.user == self.owner:
            return True
        await interaction.response.send_message('Not your game', ephemeral=True)
        return False


class Minesweeper(HideoutCog):
    @commands.command(aliases=['ms'])
    async def minesweeper(self, ctx: HideoutContext):
        """Starts an interactive game of minesweeper"""
        view = MSView(bot=ctx.bot, owner=ctx.author)
        await view.start(ctx)
