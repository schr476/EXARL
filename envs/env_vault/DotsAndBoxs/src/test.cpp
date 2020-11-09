#include "dotsAndBoxes.h"
#include "mpi.h"
#define NANOSECS 1000000000
#define RANK0(x) if(!rank) x
#define ALLRANK(x) x

uint64_t globalTimeStamp(void)
{
    struct timespec res;
    clock_gettime(CLOCK_REALTIME, &res);
    uint64_t timeRes = res.tv_sec*NANOSECS+res.tv_nsec;
    return timeRes;
}

DotsAndBoxes * board = NULL;
int boardSize = 3;
int numInitMoves = 5;

int main(int argc, char* argv[]) {
    ALLRANK(MPI_Init(NULL, NULL));
    int rank;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    
    if(argc == 3) {
        boardSize = atoi(argv[1]);
        numInitMoves = atoi(argv[2]);
    }
    
    auto initStart = globalTimeStamp();
    board = new DotsAndBoxes(boardSize);
    board->initRandom(numInitMoves, true);
    auto initEnd = globalTimeStamp();
    
    RANK0(printf("Start-------------------------\n"));
    RANK0(board->printBoard());

    fflush(stdout);
    bool endTurn = false;
    auto scoreStart = globalTimeStamp();
    // int action = rand() % 2 * boardSize * (boardSize-1);
    for(int i=0; i<2 * boardSize * (boardSize-1); i++) {
        if(board->scoreMove(i, endTurn) > -1)
            break;
    }
    auto scoreEnd = globalTimeStamp();
    
    RANK0(printf("Player 1-------------------------\n"));
    RANK0(board->printBoard());

    auto stateUpdateStart = globalTimeStamp();
    board->OpponentMove();
    auto stateUpdateEnd = globalTimeStamp();

    RANK0(printf("Player 2-------------------------\n"));
    RANK0(board->printBoard());

    auto stateStart = globalTimeStamp();
    board->serializeBoard();
    board->terminal();
    auto stateEnd = globalTimeStamp();

    RANK0(printf("Done-------------------------\n"));
    RANK0(board->printBoard());

    auto shutdownStart = globalTimeStamp();
    delete board;
    auto shutdownEnd = globalTimeStamp();
 
    RANK0(printf("Init: %lf Move: %lf Opp: %lf State: %lf Shutdown: %lf\n", (double)(initEnd-initStart)/1e9, (double)(scoreEnd-scoreStart)/1e9, (double)(stateUpdateEnd-stateUpdateStart)/1e9, (double)(stateEnd-stateStart)/1e9, (double)(shutdownEnd-shutdownStart)/1e9));
    ALLRANK(MPI_Finalize());
    return 0;
}