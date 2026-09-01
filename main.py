grille = [[" ", " ", " "], [" ", " ", " "], [" ", " ", " "]]
print(len(grille))


def render_grille():
    print(f"  |{1}|{2}|{3}|")
    print("---------")
    for i in range(len(grille)):
        print(f" {i + 1}|{grille[i][0]}|{grille[i][1]}|{grille[i][2]}|")


def verif_end():
    empty_count = 0
    for i in range(len(grille)):
        for j in range(len(grille)):
            if (
                (
                    grille[i][0] == grille[i][1]
                    and grille[i][1] == grille[i][2]
                    and grille[i][0] != " "
                )
                or (
                    grille[0][j] == grille[1][j]
                    and grille[1][j] == grille[2][j]
                    and grille[0][j] != " "
                )
                or (
                    grille[0][0] == grille[1][1]
                    and grille[1][1] == grille[2][2]
                    and grille[0][0] != " "
                )
                or (
                    grille[2][0] == grille[1][1]
                    and grille[1][1] == grille[0][2]
                    and grille[2][0] != " "
                )
            ):
                return 1
            if grille[i][j] == " ":
                empty_count += 1
    if empty_count == 0:
        return -1
    return 0


render_grille()

game_finished = 0
active_player = 0

while game_finished == 0:
    print("Coordinates? ")
    line = int(input("Line: "))
    column = int(input("Column: "))
    if active_player == 0:
        sign = "X"
    else:
        sign = "O"
    grille[line - 1][column - 1] = sign
    game_finished = verif_end()
    print("___________________")
    active_player = 1 - active_player
    render_grille()

if game_finished < 0:
    print("Draw!")
else:
    print(f"Player {sign} wins!")
