"""The merged clocked reading model of the V35S front end (model.py and model_e6.py in one).

A reading aid, not a reference: it starts at the end of the first long shift (queue full, bus
idle) and predicts every bus event to the program's end. One rule set, every rule a named option:

    python3 -m validation.v35s.qprobe.model_m [--id ...] [--waits ...] [-v] [--log] [--opt K=V ...]
    build/qp/merge/full.py      whole traces (to the END's OUT and HALT), per group
    build/qp/merge/sweep.py     option sets against the run-level union of both parents
    build/qp/merge/rivals.txt   the A-against-B rival rules, alone and combined (sweep.py input)

Notation. A routine is a list of words, one a clock; a word is a set of acts; the last word is
the boundary word (E): the staged opcode becomes the running instruction when it executes.
    N       pop the next opcode into staging            P, P2   pop one / two operand bytes
    X       post an I/O request                         Y       post a memory request
    D       wait for the EU's bus cycle to end          F       flush (a taken jump)
    B, S, A waits with no other effect: B and F for the pin cycle of a running fetch, S / A / X
            for the bus unit's setup slot (below); (G: a rejected rival, see RIVALS)
A fetch's pin cycle is 3 + w clocks, an I/O cycle 3, a memory cycle of the EU 3 + w.

THE RULES (option = default: mechanism)

Queue and prefetch
  IDLE_AT=4     a fetch starts from an idle bus when four or fewer bytes are held, on the clock
                of the pop that makes it so (seven places; a word needs two and one in hand)
  B2B_AT=5      on the clock after a fetch's last clock a fetch follows with five held (the
                word's second byte takes the seventh place) unless a boundary executes on that
                clock; with four or fewer the fetch starts and the boundary waits
  REQ_PRI=1     ... and the five-held continuation is not made when an EU request word executed
                on the fetch's last clock (five held is the lowest priority of the bus unit)
  FLUSH_LAT=5   a flush word waits for a running fetch; the target's fetch starts 5 clocks later

The instruction boundary
  (base)        no boundary while a fetch's pin cycle is in flight, except on its last clock
  E_EU=1        ... nor while an EU bus cycle is in flight, except on its last clock
  E_PEND=1      ... nor while a memory cycle is posted and not yet started (a routine with a
                memory cycle ends on that cycle's last clock at the earliest)
  FIRST_MIN=4   the first boundary after a flush waits for four bytes of the new stream
  EMIN_M=3      the boundary of a ModR/M opcode waits for three bytes behind the staged opcode
  EMIN=2        any boundary waits for two bytes behind the staged opcode

The EU's bus cycles
  POST_LAT=4    a request word's cycle starts four clocks later, or when the bus frees
  Y_LEFT=2      a memory request word (Y) is taken when the running fetch has at most one clock
                left after this one (in the fetch's last two clocks); it waits before that
  EU_HOLD=1     an I/O write's cycle starts no sooner than the clock after its routine's
                boundary (the cycle is issued by the routine's end; the request word only waits)
  EU_EPRI=1     on the clock after an EU cycle, a boundary that executes keeps the fetch that was
                pending under the cycle from starting on that clock (the fetch one clock later)

The bus unit's setup slot (what the S, A and X words wait for)
  S_LAG=2       a bus cycle's slot is its pin cycle, moved two clocks earlier for an EU cycle
                and for every fetch chained behind it (a fetch wanted while the EU cycle held the
                bus, and the fetches that follow back to back): from an EU cycle until the bus
                next goes idle the bus unit's sequencing runs two clocks ahead of the pins
  EU_SLOT=1     the EU cycle's own slot counts (OUT DW's first word waits on the first pin clock
                of the I/O cycle before it)
  LAG_ACTS=SXA  the words that wait by the slot: the long shift's 4th word (S), OUT DW's first
                word (A), an I/O request word (X); B and F words wait by the pin cycle
  LAG_FIRST=A   OUT DW's first word does not wait on the first clock of a lagged fetch's slot
  CHAIN_POP=1   a chained fetch whose first pin clock carries a pop is an ordinary fetch (its
                slot is its pin cycle): the pop restarts the request

The decode stage (runs from the pop of an opcode, before its boundary)
  LEAD_E6=3     OUT imm8 / OUT imm8,AW / IN imm8: boundary no sooner than 3 clocks after the pop
  LEAD_SR=2     MOV sreg,r16: no sooner than 2 clocks after the pop (every other opcode read: 1)
  LEAD_EPRI=1   a lead that ends on the very clock a back-to-back fetch would start: the boundary
                executes and the fetch starts one clock later
  HALT_STOP=1   HALT acts at its pop: nothing more is fetched
  HALT_HOLD=1   ... and an EU cycle not yet started is held one clock

The frame: TE / TE_W the first long shift's NXT clock; SHL_BASE=12 (+ 2 a count), SHL_B=4 the
long shift's waiting word, SHL_N=1 its NXT word from the end.

Function the model carries (not timing rules): CL and DW as the program loads them; Z after the
long shift (set) and after INC / DEC r16 (clear) chooses the taken / not-taken routine of JZ / JNZ;
the targets of JMP short / near / far, CALL near and RET.

Where the evidence is thin (build/qp/merge/drop.txt has every rule off alone): EMIN (3 runs),
LAG_FIRST and X in LAG_ACTS (one program at three waits), HALT_STOP (3), LEAD_EPRI (8, w0 only),
REQ_PRI (9), CHAIN_POP (10), EU_HOLD (16). Not read: SHL r,imm8, MULU, the read-modify-write form,
CALL / RET, the ModR/M forms of `em2-*` other than those above; JMP near, JMP far and Jcc taken
are reproduced in part only (their shapes below are the best found, not a reading).

RIVALS (rejected; kept as switches so the deciding counts can be re-run, build/qp/merge/rivals.txt)
  B_FROM=1      model.py's B_FROM=3: B words wait only from a fetch's third clock
  SHL_ACT=S     model.py's long shift waited as a B word ("B")
  Y_MODE=late   model.py's Y "none" (no wait); model_e6.py's "slot" (as X); "pin" (whole cycle)
  act G         model.py's OUT DW / store ending: the word completes the clock before the cycle

ROUND 16 (results Q61-Q67)
  The 0F page: every form releases its ModR/M byte on its third word, a bus-idle word (`P . BP`);
  the r,imm / ROL4 / ROR4 / EXT / INS forms are one word shorter in front of the commit word than
  rounds 9-12 had them, the m,CL forms one word longer. EXT / INS take offset and length from
  any 8-bit register and leave the offset register at offset + length (BF_OFF). LAHF is `N .`.
  CALL / JMP [d16]: `P . B Y . PP2 D ...`. Tested and not kept (switches left in): act H (a word
  that waits as a boundary does), OF2 (0F as a routine of its own with a second boundary),
  EMIN_K (a per-form byte count at the boundary), B_CH (a bus-idle word losing to the fetch
  chained behind a post-write fetch).

(round 17) LEA per EA mode: five words in every mode, the displacement released with the next
opcode on the bus-idle fourth word (P . . BN<disp> .), one word more for two registers and a
d16 (keys LEA / LEAX / LEA_D8 / LEAX_D8 / LEA_D16 / LEAX_D16 / LEA_DIR). The 81 group on memory
with a displacement (ADDIW_D8 / _D16 / _DIR, CMPIW_D16 / _DIR, ADDIM_D16). YP_UN=1 with
ARB_K="WR": a read whose request word also releases the displacement is treated as Q33 treats
the unarmed write (it competes from its due clock; Q69). CVTBD is 21 words with a bus-idle
sixth word.

(round 20) act I: a bus-idle word that also waits on the clock a back-to-back / chained fetch
starts (no exemption), and for which a chained fetch is not held back once the word is reached.
It is the release word of LEA with d16 / direct and of MOV r16,imm16, and the segment word of
JMP far / CALL far (results Q88, Q89).
"""

from __future__ import annotations

import argparse
import sys

from . import read

DEFAULT = dict(
    IDLE_AT=4, B2B_AT=5, REQ_PRI=1, FLUSH_LAT=5, H_B2B=1, H_EU=1, B_CH=0, B_CH_W=1, EMIN_K=0, EMIN_KEYS="ADDIM_DIR", OF2=0, OF_PFX="N .", OF_DROP=2, LEAD_0F=2, OF_EMIN=0, BF_OFF=1, EXTRX_D=0, INSRX_D=0,
    RSV_KEYS="", B_EU="OIWR", B_EU_LAST="", B_EU_OF=0, B_B2B=0, SHL_ZERO=2, CH_EPRI=1, CH_BNEXT=1, C_NOCH=3, E_C=0, CH_K="W", EMIN_J=2, PREP_HEAD=". . Y D . . . PP2 P . . C . . . . . . .",
    PREP_COPY="U D . . . Z D . .", PREP_HEAD2=". . Y D . . . PP2 P . . C . . . . . .", PREP_TAIL=". Z D . . . . N .", H_4S="P . . B . . . . . . . . .",
    I_ADD4S="Y D . . . U D . . . . . . Z D .", T_ADD4S=". . . . . . . . N .",
    I_CMP4S="Y D . . . U D . . . . . . . .", T_CMP4S=". . . . . . . . . N .", EXT_HEAD="P . BP . C . . Y DP . B", EXTI_TAIL="N .", EXT_BASE=24, EXT_K=4, EXTX_GAP=23, EXTX_BASE=12, INSX_1=65, INSX_GAP=8, INSX_BASE=17, INS_BASE=70, EXTR_HEAD="P . BP . C . Y D", EXTR_BASE=24, INSR_BASE=70, LAG_B2B=0, LAG_K="W", ARB=3, ARB_K="WR", YP_UN=1, MD4B=25, MD5B=36, MD6B=33, MD7B=52, MD4W=33, MD5W=43, MD6W=41, MD7W=60, MD_B=2, MM_ADD=0, MI16=41, MI8=40, MI_P=4, MI_ACTS="2:B,4:B", T_N=2, MD_MNEG=8, MD_QNEG=2, MD_DNEG=7, REP_CMP_N=2, V_NOPRI=1, SHLI_AS_CL=1, SHLI_ACT="S", SHLI_W3="BP", SHLI_AT=5, SHLI_D=-1, E_EU=1, E_PEND=1, FIRST_MIN=4, EMIN_M=3, EMIN=2, LEAD_EU_END=0,
    POST_LAT=4, Y_LEFT=2, EU_HOLD=1, EU_EPRI=1, Z_LAT=2, FLUSH_B2B=1, FLUSH_GAP=3,
    S_LAG=2, EU_SLOT=1, V_LAG=0, INSI_HEAD="P . BP . C . . Y DP . . B", EXTI_D=2, INSI_D=3, P2_Q=0, LCH=3, LCH_K="R", LCH_MIN=1, RIPE4=0, LCH_Y=0, LCH_AFTER="WROI", LAG_ACTS="SXA", LAG_FIRST="A", CHAIN_POP=1,
    LEAD_E6=3, LEAD_SR=2, LEAD_CC=0, LEAD_FF=0, LEAD_E2=2, LEAD_EPRI=1, HALT_STOP=1, HALT_HOLD=1,
    TE=79, TE_W=2, SHL_N=1, SHL_B=4, SHL_BASE=12,
    # the rejected rivals (see the docstring)
    B_FROM=1, B_ACTS="B", SHL_ACT="S", Y_MODE="late",
    # routines, read in rounds 1-3 (model.py)
    NOP="N...", INC="N.", RR="PN .", RI=". . . . BINPP2 .", MOVI8=". . . BNP .", XCHG="N...",
    CLC="N.", CBW="N..", ADDI=". . . . BINPP2 .", ADD83="P . . BNP .", ADDRR="PN .", RR8="PN .",
    PFX="N.", SHL1="P . B . . B . N .", JMP=". . . BP . . F N .", JZ=". . . BP . . . B . . F N .",
    JNZ=". . . BP . . BN .", ADDAL=". . . BNP .", SR="PN .",
    # I/O (model_e6.py): port byte on word 4; `X . N .` and the cycle after the boundary
    OUT="A . X . N .", E6=". . . BP . . X . N .", IN8=". . . BP . . X DN .",
    # memory: the request (Y), then the datum's wait (D) or, for a write, the boundary's wait
    PUSH=". . Y . . . N .", POP=". . Y DN .", LD=". . Y PP2 DN .", ST=". . Y PP2 G N .",
    PUSHI=". . . . PP2 . Y N", PUSHI8=". . . P . Y N", LAHF="N.", CMPMR="P Y . D . N .", NEGD16="P . . B Y . PP2 . DZ G N .", ADJ4=". . . . . . . . N .", ADJB=". . . . . . . . . . . . . . . N .",
    CVTBD=". . . BP . B . . . . . . . . . . . . . N .", EI=". . . . . . . . . . . N .", CVTWL=". . . . . . . N .",
    SHMI_HEAD="P . V DP . B", SHMI_BASE=4, SHMCL_HEAD="P . . B . . . Y D", SHMCL_BASE=3,
    LDS="P Y . D . U . D . . N .", MOVMS="P . V . G N .", MOVSM="P Y . DN . .",
    MI16M="P . . BY DPP2 . B . B . . . . . . . . . . . . . . . . . . . . . . . . . . . . N .",
    MI8M="P . V DP . B . B . . . . . . . . . . . . . . . . . . . . . . . . . . . . N .", POPF=". . Y D . N .",
    L_BW="P Y . DN .", L_BI="P Y . DN .", L_D8="P Y . P DN .", L_D16="P Y . PP2 DN .",
    L_DIR="P Y . PP2 DN .", S_BW="P Y . G N .", S_D8="P Y . P G N .", S_DIR="P Y . PP2 G N .",
    L_A0="P Y . DN .", L_A1="P Y . P DN .", L_A2="P Y . PP2 DN .",
    S_A0="P Y . G N .", S_A1="P Y . P G N .", S_A2="P Y . PP2 G N .",
    L_A2X="P . Y . PP2 DN .", S_A2X="P . Y . PP2 G N .",
    # jumps other than JMP short: best shapes found, reproduced in part (not a reading)
    JN=". . . . PP2 . . F N .", JFAR=". . . . PP2 . Q . BIPP2 . . F N .",
    # not read (placeholders: these groups are not reproduced)
    SHLI="PN P . .", MUL8="PN . . .", CALL=". . . . PP2 . Y D . . F N .",
    RET=". . Y D . . F N .", XCHRR="PN .", TESTRR="P . BN .",
    INCB="P . . BN .", TEST1="P . BP . . BN .", CLR1="P . BP . . BN . .", RMW="P Y . . DZ G N .",
    ADDIW="P . . BY DPP2Z G N .", ADDIM_D8="P . V P DPZ G N .", ADDIW_D8="P . . BYP DPP2Z G N .", ADDIW_D16="P . . BIYPP2 DPP2Z G N .", ADDIW_DIR="P . . BIYPP2 DPP2Z G N .", CMPIW_D16="P . . BIYPP2 DPP2 . BN .", CMPIW_DIR="P . . BIYPP2 DPP2 . BN .", ADDIM_D16="P . V PP2 DPZ G N .",
    ADDIM_DIR="P . V PP2 DPZ G N .", CALLMB="P . B Y D . . . Z D . . F N .", JMPMB="P . B Y D . . F N .", CALLFMB="P . B Y D . U D . . . Z D . . . Z D . . F N .", JMPFMB="P . B Y D . U D . . F N .", S1M_D8="P . BP . . C Y . P DZ G N .", S1M_D16="P . BP . . C Y . PP2 DZ G N .", C1M_D8="P . BP . . C Y . P D Z G N .", C1M_D16="P . BP . . C Y . PP2 D Z G N .", T1M_D8="P . BP . . C Y . P DN .", T1M_D16="P . BP . . C Y . PP2 DN .", SHLM1_D16="P . B Y . PP2 D . . . . . Z G N .", RMW_D16="P Y . PP2 DZ G N .", RMW_X16="P . Y . PP2 DZ G N .", XCHM_DIR="P Y . PP2 D . Z G N .", STIM_X16="P . . . BIYPP2 . . . KPP2N .", TESTAI=". . . . BINPP2 .", CVTDB=". . . BP C . . . . . . . . . . . . N .", DIK=". . BN .", CMPIM_DIR="P . V PP2 DP . BN .", CMPM_D16="P Y . PP2 DN .", CMPIM="P . V DP . BN .", TESTIM="P . B . . Y DPP2 . BN .",
    TESTM="P . B Y DN .", XCHM="P Y . . D . Z G N .", STIM_D8="P . . BYP . . . KPP2N .",
    STIMB="P . V . . . KPN .", STIM_D16="P . . BIYPP2 . . . KPP2N .", NOTM="P . . B Y . . DZ G N .",
    INCMB="P . . B Y . . DZ G N .", SHLM1="P . B Y D . . . . . Z G N .", PUSHM="P . B Y D . . . Z G N .",
    PUSHM_D8="P . . B Y P D . . . Z G N .", PUSHM_DIR="P . . B Y P P2 D . . . Z G N .",
    POPM="P . Y D . . Z G N .", POPM_D8="P . Y D . . PZ G N .", POPM_DIR="P . Y D . . PP2Z G N .", CMPRR="PN .", NOTR="P . . BN .", MOVS=". . . . . Y D . . . Z DN .",
    STOS=". . B . . . Y G N .", LODS=". . . . Y DN .", INDW=". . X DN .", XLAT=". . Y DN .", LEA="P . . BN .", LEAX="P . . BN .", LEA_D8="P . . BNP .", LEAX_D8="P . . BNP .", LEA_D16="P . . BINPP2 .", LEAX_D16="P . . . BINPP2 .", LEA_DIR="P . . BINPP2 .",
    CALLF=". . . . PP2 . Q . BIPP2 . Y D . Y D . . F N .", RETF=". . Y D . Y D . . F N .", JR="P . B . B . . F N .", INT3=". . B . B . . Y . . . . . . . DZ D . . U . . . . . DZ D . . . Z D . . F N .", LOOP=". . . B . . P . . B . . F N .", CMPBK=". . . . . Y D . . . U D . N .", SCAS=". . . . . . Y D . . N . .", INM=". . . . . X D Z DN .", OUTM=". . . . B . Y D . X . . . N .", REP_ZERO=". . . B . . . . . . N .", REP_HEAD=". . . B . . . . . . . . . .",
    RI_MOVS="Y D . . . Z D .", RT_MOVS=". . . . . . N .", RI_STOS="Y D .",
    RT_STOS=". . . . . . N .", RI_LODS="Y D . . .", RT_LODS=". . . . . . . N .",
    RI_SCAS="Y D . .", RT_SCAS=". . . . . . . . . . . . N .", RH_CMPBK=". . . B . . . . . . . . .", RH_OUTM=". . . . B . . . . . . . . . .", RI_CMPBK="Y D . . . U D .",
    RT_CMPBK=". . . . . . . . . . . . . . N .", RH_INM=". . . . B . . . . . . . . .", RI_INM="X D Z D", RT_INM=". . . . . . . N .",
    RI_OUTM="Y D X . . . . .", RL_OUTM="Y D . X . . . . .", RT_OUTM=". . . . . . . N .",
    PUSHA=". . B . " + "Y D . " * 7 + "Y G N .", POPA=". . " + "Y D . " * 7 + "Y DN .", TEST1I="P . BP . BPN .", T1M="P . BP . . C Y DN .", C1M="P . BP . . C Y D Z G N .", S1M="P . BP . . C Y DZ G N .",
    T1MI="P . PC Y DPN .", C1MI="P . PC Y DP Z G N .", S1MI="P . PC Y DPZ G N .",
    CLR1I="P . BP . BPN . .", ROR4="P . BP . C . . . . . . . . . . . . . . N .", ROL4M="P . PC Y D . . . . . . . . Z G N .", ROR4M="P . PC Y D . . . . . . . . . . . . Z G N .",
    ADD4S="P N .", SUB4S="P N .", CMP4S="P N .", INS="PP2N .", EXT="PP2N .", INSI="PP2N .", EXTI="PP2N .",
    PREP=". . Y D . . . PP2 P . . C . . . . . . . . N .", DISP=". . Y DN .", BRK=". . . BP . B . . Y . . . . . . . DZ D . . U . . . . . DZ D . . . Z D . . F N .", AI16R="P . . . BINPP2 .", TI16R="P . B . . . NPP2 .", TI8R="P . B . . NP .", CALLR="P . B . . B . Y D . . F N .", CALLM="P . B Y . PP2 D . . . Z D . . F N .",
    JMPM="P . B Y . PP2 D . . F N .", RETI=". . . Y DPP2 . . F N .", CMPIW="P . . BY DPP2 . BN .", CMPIW_D8="P . . BYP DPP2 . BN .",
    RI_SCAS_C="Y D . . . .", RT_SCAS_C=". . . . . . . . . . . N .",
    RT_CMPBK_C=". . . . . . . . . . . . . N .", LOOPZ=". . . B . . . P . . B . . F N .", LOOPZF=". . . B . . PN .", LOOPZ0=". . . B . . . P . BN .", LOOPZ00=". . . B P . BN .",
    JMPFM="P . B . Y PP2 D . U D . . F N .", CALLFM="P . B . Y PP2 D . U D . . . Z D . . . Z D . . F N .",
    IRET=". . Y D . . . U D . . . U D . . . . . . . . F N .", LOOPN=". . . B . . P . BN .", JCXZT=". . . B . . P . . F N .", JCXZ=". . . B . . PN .", PUSHS=". . . Y . . . N .", POPS=". . Y DN . .", ROL4="P . BP . C . . . . . . . . . . N .", SHLI1="PP2N . .",
    RMW_D8="P Y . P DZ G N .", INCM="P . . B Y . . DZ G N .", ADDIM="P . V DPZ G N .",
    STIM="P . . BY . . . KPP2N .", STIM_DIR="P PP2 . PP2 Y N", ADDM="P Y . DN .", CMPM="P Y . DN .",
    # (round 20, Q90) read from QPr20a
    TESTM_DIR="P . B Y . PP2 DN .", TESTM_D16="P . B Y . PP2 DN .",
    TESTIM_D16="P . B . . BIYPP2 DPP2 . BN .", TESTIM_D8="P . B . . BYP DPP2 . BN .",
    TESTIM_DIR="P . B . . BIYPP2 DPP2 . BN .", NEGD8="P . . B Y . P . DZ G N .",
    NEGDIR="P . . B Y . PP2 . DZ G N .", NOTD16="P . . B Y . PP2 . DZ G N .",
    INCD16="P . . B Y . PP2 . DZ G N .", POPM_X16="P . Y D . . . PP2Z G N .",
    POPM_D16="P . Y D . . PP2Z G N .", POPM_X8="P . Y D . . PZ G N .")

# opcode -> (routine key, the kind of its bus request, has a ModR/M byte)
OPS = {0x90: ("NOP", None, 0), 0x43: ("INC", None, 0), 0x4B: ("INC", None, 0),
       0x42: ("INC", None, 0), 0x4A: ("INC", None, 0),
       0x8B: ("RR", None, 1), 0xEE: ("OUT", "O", 0), 0xEF: ("OUT", "O", 0),
       0xE6: ("E6", "O", 0), 0xE7: ("E6", "O", 0), 0xE4: ("IN8", "I", 0),
       0xBB: ("RI", None, 0), 0xBA: ("RI", None, 0), 0xB8: ("RI", None, 0),
       0xB1: ("MOVI8", None, 0), 0xB3: ("MOVI8", None, 0), 0xB0: ("MOVI8", None, 0), 0xB2: ("MOVI8", None, 0),
       0xEB: ("JMP", None, 0), 0x93: ("XCHG", None, 0), 0xF8: ("CLC", None, 0), 0xFB: ("EI", None, 0), 0xFA: ("DIK", None, 0), 0xA9: ("TESTAI", None, 0), 0x3D: ("TESTAI", None, 0), 0xD5: ("CVTDB", None, 0),
       0x98: ("CBW", None, 0), 0x99: ("CVTWL", None, 0), 0x92: ("XCHG", None, 0), 0xED: ("INDW", "I", 0), 0xA8: ("ADDAL", None, 0), 0x3C: ("ADDAL", None, 0),
       0x9F: ("LAHF", None, 0), 0x27: ("ADJ4", None, 0), 0x37: ("ADJB", None, 0), 0x3F: ("ADJB", None, 0),
       0xD4: ("CVTBD", None, 0), 0x6A: ("PUSHI8", "W", 0), 0x05: ("ADDI", None, 0), 0x83: ("ADD83", None, 1),
       0x03: ("ADDRR", None, 1), 0x8A: ("RR8", None, 1), 0x26: ("PFX", None, 0), 0xF3: ("PFX", None, 0), 0xF2: ("PFX", None, 0),
       0xD1: ("SHL1", None, 1), 0xC1: ("SHLI", None, 1), 0xC0: ("SHLI", None, 1), 0xF6: ("MUL8", None, 1),
       0xE9: ("JN", None, 0), 0x74: ("JZ", None, 0), 0x75: ("JNZ", None, 0),
       0xA1: ("LD", "R", 0), 0xA3: ("ST", "W", 0), 0x50: ("PUSH", "W", 0),
       0x58: ("POP", "R", 0), 0xD3: ("SHL", None, 1), 0xF4: ("HALT", None, 0),
       0x04: ("ADDAL", None, 0), 0x68: ("PUSHI", "W", 0), 0x9D: ("POPF", "R", 0),
       0x8E: ("SR", None, 1), 0xE8: ("CALL", "W", 0), 0xC3: ("RET", "R", 0),
       0xEA: ("JFAR", None, 0), 0x86: ("XCHRR", None, 1), 0x84: ("TESTRR", None, 1),
       0xFE: ("INCB", None, 0), 0x0F: ("TEST1", None, 1),
       0x3B: ("CMPRR", None, 1), 0xF7: ("NOTR", None, 0), 0xA4: ("MOVS", "R", 0),
       0xAA: ("STOS", "W", 0), 0xAB: ("STOS", "W", 0), 0xC8: ("PREP", "W", 0), 0xC9: ("DISP", "R", 0), 0x60: ("PUSHA", "W", 0), 0x61: ("POPA", "R", 0), 0xA6: ("CMPBK", "R", 0), 0xA7: ("CMPBK", "R", 0), 0xAE: ("SCAS", "R", 0), 0xAF: ("SCAS", "R", 0), 0x6C: ("INM", "I", 0), 0x6D: ("INM", "I", 0), 0x6E: ("OUTM", "R", 0), 0x6F: ("OUTM", "R", 0), 0xAC: ("LODS", "R", 0), 0xAD: ("LODS", "R", 0), 0xA5: ("MOVS", "R", 0), 0x8C: ("RR", None, 1),
       0x1E: ("PUSHS", "W", 0), 0x1F: ("POPS", "R", 0), 0x9C: ("PUSH", "W", 0),
       0xEC: ("INDW", "I", 0), 0xD7: ("XLAT", "R", 0), 0x8D: ("LEA", None, 1),
       0xE2: ("LOOP", None, 0), 0xE0: ("LOOP", None, 0), 0xE1: ("LOOP", None, 0), 0x64: ("PFX", None, 0), 0xF0: ("PFX", None, 0), 0x65: ("PFX", None, 0), 0xCF: ("IRET", "R", 0), 0xE3: ("JCXZ", None, 0), 0x9A: ("CALLF", "W", 0),
       0xCB: ("RETF", "R", 0), 0xC2: ("RETI", "R", 0), 0xFF: ("JR", None, 1), 0xCC: ("INT3", "R", 0), 0xCD: ("BRK", "R", 0),
       0xB9: ("RI", None, 0), 0xBE: ("RI", None, 0), 0xBF: ("RI", None, 0)}

# memory forms: (opcode, ModR/M byte) -> (routine key, bus kind, has ModR/M)
MEM = {(0x8B, 0x07): ("L_BW", "R", 1), (0x8A, 0x07): ("L_BW", "R", 1), (0x88, 0x07): ("S_BW", "W", 1), (0x8B, 0x47): ("L_D8", "R", 1),
       (0x8B, 0x87): ("L_D16", "R", 1), (0x8B, 0x00): ("L_BI", "R", 1),
       (0x8B, 0x06): ("L_DIR", "R", 1), (0x89, 0x07): ("S_BW", "W", 1),
       (0x89, 0x47): ("S_D8", "W", 1), (0x89, 0x06): ("S_DIR", "W", 1),
       (0x01, 0x07): ("RMW", "R", 1), (0x01, 0x47): ("RMW_D8", "R", 1),
       (0xFF, 0x07): ("INCM", "R", 1), (0x83, 0x07): ("ADDIM", "R", 1),
       (0xC7, 0x07): ("STIM", "W", 1), (0x03, 0x07): ("ADDM", "R", 1),
       (0x3B, 0x07): ("CMPM", "R", 1), (0xC7, 0x06): ("STIM_D16", "W", 1),
       # (round 9)
       (0x81, 0x07): ("ADDIW", "R", 1), (0x81, 0x3F): ("CMPIW", "R", 1), (0x81, 0x7F): ("CMPIW_D8", "R", 1), (0x83, 0x47): ("ADDIM_D8", "R", 1),
       (0x83, 0x06): ("ADDIM_DIR", "R", 1), (0x08, 0x07): ("RMW", "R", 1), (0x28, 0x07): ("RMW", "R", 1), (0x10, 0x07): ("RMW", "R", 1), (0x18, 0x07): ("RMW", "R", 1),
       (0x20, 0x07): ("RMW", "R", 1), (0x30, 0x07): ("RMW", "R", 1), (0x09, 0x07): ("RMW", "R", 1), (0x11, 0x07): ("RMW", "R", 1),
       (0x31, 0x07): ("RMW", "R", 1), (0xFF, 0x8F): ("INCD16", "R", 1), (0xD1, 0xA7): ("SHLM1_D16", "R", 1),
       (0x01, 0x87): ("RMW_D16", "R", 1), (0x01, 0x80): ("RMW_X16", "R", 1), (0x01, 0x06): ("RMW_D16", "R", 1),
       (0x87, 0x06): ("XCHM_DIR", "R", 1), (0xC7, 0x80): ("STIM_X16", "W", 1), (0xC7, 0x40): ("STIM_D8", "W", 1), (0x83, 0x3E): ("CMPIM_DIR", "R", 1), (0x3B, 0x87): ("CMPM_D16", "R", 1), (0x83, 0x3F): ("CMPIM", "R", 1),
       # (round 17) the 81 / 83 group with a displacement
       (0x81, 0x47): ("ADDIW_D8", "R", 1), (0x81, 0x87): ("ADDIW_D16", "R", 1),
       (0x81, 0x06): ("ADDIW_DIR", "R", 1), (0x81, 0xBF): ("CMPIW_D16", "R", 1),
       (0x81, 0x3E): ("CMPIW_DIR", "R", 1), (0x83, 0x87): ("ADDIM_D16", "R", 1),
       (0xF7, 0x07): ("TESTIM", "R", 1), (0x85, 0x07): ("TESTM", "R", 1),
       (0x87, 0x07): ("XCHM", "R", 1), (0xC7, 0x47): ("STIM_D8", "W", 1),
       (0xC6, 0x07): ("STIMB", "W", 1), (0xC7, 0x00): ("STIM", "W", 1),
       (0xC7, 0x87): ("STIM_D16", "W", 1), (0xF7, 0x17): ("NOTM", "R", 0),
       (0xFE, 0x07): ("INCMB", "R", 0), (0xD1, 0x27): ("SHLM1", "R", 1),
       (0xFF, 0x0F): ("INCM", "R", 1), (0xFF, 0x37): ("PUSHM", "R", 1),
       (0xFF, 0x77): ("PUSHM_D8", "R", 1), (0xFF, 0x36): ("PUSHM_DIR", "R", 1),
       (0x8F, 0x07): ("POPM", "R", 1), (0x8F, 0x47): ("POPM_D8", "R", 1),
       (0x8F, 0x06): ("POPM_DIR", "R", 1),
       # (round 14)
       (0x80, 0x07): ("ADDIM", "R", 1), (0x80, 0x0F): ("ADDIM", "R", 1),
       (0x80, 0x3F): ("CMPIM", "R", 1), (0xC1, 0x27): ("SHMI", "R", 1),
       (0xC0, 0x27): ("SHMI", "R", 1), (0xD3, 0x27): ("SHMCL", "R", 1),
       (0xD2, 0x27): ("SHMCL", "R", 1), (0xC5, 0x07): ("LDS", "R", 1),
       (0xC4, 0x07): ("LDS", "R", 1), (0x8C, 0x1F): ("MOVMS", "W", 1),
       (0x8E, 0x07): ("MOVSM", "R", 1), (0x69, 0x07): ("MI16M", "R", 1),
       (0x6B, 0x07): ("MI8M", "R", 1),
       # by analogy only (the interrupt class trains; not form probes): ALU m,r as ADD m,r
       (0x00, 0x07): ("RMW", "R", 1), (0x29, 0x07): ("RMW", "R", 1), (0x21, 0x07): ("RMW", "R", 1),
       (0x31, 0x07): ("RMW", "R", 1), (0x11, 0x07): ("RMW", "R", 1), (0x09, 0x07): ("RMW", "R", 1),
       (0x39, 0x07): ("CMPMR", "R", 1), (0x38, 0x07): ("CMPMR", "R", 1), (0x19, 0x07): ("RMW", "R", 1),
       (0xFF, 0x0F): ("INCM", "R", 1), (0xF7, 0x1F): ("NOTM", "R", 0),
       (0xF7, 0x9F): ("NEGD16", "R", 1),
       # (round 20) forms that had no probe of their own
       (0x85, 0x06): ("TESTM_DIR", "R", 1), (0x85, 0x87): ("TESTM_D16", "R", 1),
       (0xF7, 0x87): ("TESTIM_D16", "R", 1), (0xF7, 0x47): ("TESTIM_D8", "R", 1),
       (0xF7, 0x06): ("TESTIM_DIR", "R", 1), (0xF7, 0x5F): ("NEGD8", "R", 1),
       (0xF7, 0x1E): ("NEGDIR", "R", 1), (0xF7, 0x97): ("NOTD16", "R", 1),
       (0xFF, 0x87): ("INCD16", "R", 1), (0x8F, 0x80): ("POPM_X16", "R", 1),
       (0x8F, 0x87): ("POPM_D16", "R", 1), (0x8F, 0x40): ("POPM_X8", "R", 1)}

# the decode stage's leads: the boundary no sooner than this many clocks after the opcode's pop
LEADS = {0xE6: "LEAD_E6", 0xE7: "LEAD_E6", 0xE4: "LEAD_E6", 0x8E: "LEAD_SR", 0xE2: "LEAD_E2"}


OF_LEAD2 = set(range(0x18, 0x20)) | {0x28, 0x2A, 0x31, 0x33, 0x39, 0x3B}
STACK_OPS = (0x9C, 0x9D, 0xE8, 0xC3, 0x9A, 0xCB, 0x68, 0x06, 0x07, 0x0E, 0x16, 0x17, 0x1E, 0x1F)
REPS = ("MOVS", "STOS", "LODS", "SCAS", "CMPBK", "INM", "OUTM")


def info(code, at):
    """(routine key, bus kind, has ModR/M) of the instruction at `at`."""
    op = code[at]
    if (op, code[at + 1]) in MEM:
        return MEM[(op, code[at + 1])]
    if op == 0x0F:
        # (round 12) the 0F page beyond TEST1 / SET1 / NOT1 / CLR1 r,CL and the r,imm forms
        sub, mem = code[at + 1], code[at + 2] < 0xC0
        k = {0x10: "T1M", 0x11: "T1M", 0x12: "C1M", 0x13: "C1M", 0x14: "S1M", 0x15: "S1M",
             0x16: "S1M", 0x17: "S1M", 0x18: "T1MI", 0x19: "T1MI", 0x1A: "C1MI", 0x1B: "C1MI",
             0x1C: "S1MI", 0x1D: "S1MI", 0x1E: "S1MI", 0x1F: "S1MI", 0x28: "ROL4M",
             0x2A: "ROR4M"} if mem else {0x1A: "CLR1I", 0x1B: "CLR1I", 0x2A: "ROR4"}
        k = {**k, 0x20: "ADD4S", 0x22: "SUB4S", 0x26: "CMP4S", 0x31: "INS", 0x33: "EXT",
             0x39: "INSI", 0x3B: "EXTI"}
        if sub in k:
            if mem and k[sub] in ("S1M", "C1M", "T1M") and code[at + 2] & 0xC7 not in (0x00, 0x07, 0x01, 0x02, 0x03, 0x04, 0x05):
                md = code[at + 2] & 0xC7     # (round 21) the memory forms by CL with a displacement
                return (k[sub] + ("_D16" if md == 0x06 or md >= 0x80 else "_D8"), "R", 1)
            return (k[sub], "R" if mem or sub in (0x20, 0x22, 0x26, 0x31, 0x33, 0x39, 0x3B) else None, 0 if sub in (0x20, 0x22, 0x26) else 1)
    if op == 0x0F and code[at + 1] in (0x12, 0x13) and code[at + 2] >= 0xC0:
        return ("CLR1", None, 1)        # (round 10) CLR1 r,CL: one word longer than TEST1
    if op == 0x0F and code[at + 1] in (0x18, 0x19, 0x1C, 0x1D, 0x1E, 0x1F) and code[at + 2] >= 0xC0:
        return ("TEST1I", None, 1)      # (round 11) TEST1 / SET1 / NOT1 r,imm
    if op in (0xF6, 0xF7) and code[at + 1] < 0xC0 and (code[at + 1] >> 3) & 7 >= 4:
        # (round 12) MULU / MUL / DIVU / DIV on memory: the register routine behind a read
        return (f"MM{(code[at + 1] >> 3) & 7}{'BW'[op & 1]}", "R", 0)
    if op == 0xFF and code[at + 1] in (0x17, 0x27, 0x1F, 0x2F):     # (round 21) CALL / JMP near / far [BW]
        return ({0x17: "CALLMB", 0x27: "JMPMB", 0x1F: "CALLFMB", 0x2F: "JMPFMB"}[code[at + 1]], "R", 1)
    if op == 0xFF and code[at + 1] in (0x1E, 0x2E):       # (round 13) CALL / JMP far [d16]
        return ("CALLFM" if code[at + 1] == 0x1E else "JMPFM", "R", 1)
    if op == 0xFF and (code[at + 1] >> 3) & 7 in (2, 4) and (code[at + 1] >= 0xC0
                                                          or code[at + 1] & 0xC7 == 0x06):
        # (round 12) CALL / JMP through a register or a direct word
        k = ("CALLR", "JR") if code[at + 1] >= 0xC0 else ("CALLM", "JMPM")
        call = (code[at + 1] >> 3) & 7 == 2
        return (k[0] if call else k[1], "W" if call and code[at + 1] >= 0xC0 else
                "R" if code[at + 1] < 0xC0 else None, 0 if code[at + 1] >= 0xC0 else 1)
    if op in (0x69, 0x6B) and code[at + 1] >= 0xC0:
        return ("MI16" if op == 0x69 else "MI8", None, 1)
    if op in (0x80, 0x81, 0x83) and code[at + 1] >= 0xC0:      # (round 12) ALU r,imm
        return ("AI16R" if op == 0x81 else "ADD83", None, 1)
    if op in (0xF6, 0xF7) and 0xC0 <= code[at + 1] < 0xC8:     # (round 12) TEST r,imm
        return ("TI16R" if op == 0xF7 else "TI8R", None, 0)
    if op in (0xF6, 0xF7) and code[at + 1] >= 0xE0:
        # (round 11) MULU / MUL / DIVU / DIV on a register: MD<reg field><B|W>, a length
        return (f"MD{(code[at + 1] >> 3) & 7}{'BW'[op & 1]}", None, 0)
    if op == 0x0F and code[at + 1] == 0x28:
        return ("ROL4", None, 1)
    if op == 0xC1 and code[at + 2] == 1:
        return ("SHLI1", None, 1)
    if op == 0x8D:
        # (round 17) LEA per EA mode: LEA (no displacement), LEA_D8, LEA_D16 (direct too),
        # with X appended for the two-register modes
        m = code[at + 1]
        nd = 2 if (m >> 6) == 2 or (m & 0xC7) == 0x06 else (m >> 6)
        x = "X" if (m & 7) < 4 else ""
        d = "_DIR" if (m & 0xC7) == 0x06 else ("", "_D8", "_D16")[nd]
        return ("LEA" + x + d, None, 1)
    if op in (0x8B, 0x89) and code[at + 1] < 0xC0:
        # (round 8) the EA modes not measured one by one: the measured heads by analogy, by
        # the number of displacement bytes (keys L_A0 / L_A1 / L_A2, S_A0 / S_A1 / S_A2)
        m = code[at + 1]
        nd = 2 if (m >> 6) == 2 or (m & 0xC7) == 0x06 else (m >> 6)
        x = "X" if (m >> 6) == 2 and (m & 7) < 4 else ""     # base + index + d16: one more word
        return (("L_A" if op == 0x8B else "S_A") + str(nd) + x, "R" if op == 0x8B else "W", 1)
    return OPS[op]


def words(spec):
    """'PN .' -> [{'P','N'}, set()]. Words are separated by spaces when any word has more
    than one act, else one character each; '.' is a word with no act."""
    if isinstance(spec, list):
        return [set(w) for w in spec]

    def one(w):
        acts = set()
        if "P2" in w:
            acts.add("P2")
            w = w.replace("P2", "")
        return acts | set(w.replace(".", ""))
    if " " in spec:
        return [one(w) for w in spec.split(" ")]
    return [one(w) for w in spec]


def routine(op, o, cl=31, key=None):
    if key in ("SHMI", "SHMCL"):
        # (round 14) a shift on memory by imm8 / CL: the register routine's count loop
        # (base + 2n words) behind a read head, the write in place of the tail
        return words(o[key + "_HEAD"] + " ." * (o[key + "_BASE"] + 2 * cl) + " Z G N .")
    if op == 0xD3:
        # (round 11) a count of zero: two words fewer (seen behind REP, which leaves CW = 0)
        w = [set() for _ in range(o["SHL_BASE"] + 2 * cl - (o["SHL_ZERO"] if cl == 0 else 0))]
        w[0] = {"P"}
        if o["SHL_B"]:
            w[o["SHL_B"] - 1] = w[o["SHL_B"] - 1] | {o["SHL_ACT"]}
        w[len(w) - 1 - o["SHL_N"]] = w[len(w) - 1 - o["SHL_N"]] | {"N"}
        return w
    if op in (0xC0, 0xC1) and key in ("SHLI", "SHLI1") and o["SHLI_AS_CL"]:
        # (round 9) shift by imm8 on a register: the CL form's routine, 12 + 2n words, the
        # count byte released on the bus-idle 4th word
        w = [set() for _ in range(o["SHL_BASE"] + 2 * cl + o["SHLI_D"])]
        w[0] = {"P"}
        w[3] = set(o["SHLI_W3"])
        if o["SHLI_ACT"]:
            w[o["SHLI_AT"]] = w[o["SHLI_AT"]] | set(o["SHLI_ACT"])
        w[len(w) - 1 - o["SHL_N"]] = w[len(w) - 1 - o["SHL_N"]] | {"N"}
        return w
    if key in ("MI16", "MI8"):          # (round 12) MUL r,r/m,imm on a register
        w = [set() for _ in range(o[key])]
        w[0] = {"P"}
        ip_ = o["MI_P"] if key == "MI16" else o["MI_P"] - 1
        w[ip_] = {"P", "P2"} if key == "MI16" else {"P"}
        for item in o["MI_ACTS"].split(","):      # "offset from the immediate's word:act"
            if item:
                k_, a_ = item.split(":")
                w[ip_ + int(k_)] = w[ip_ + int(k_)] | {a_}
        w[len(w) - 2] = {"N"}
        return w
    if key and key.startswith("MM"):
        w = [set() for _ in range(o["MD" + key[2:]] + o["MM_ADD"])]
        w[0], w[2], w[3], w[4] = {"P"}, {"B"}, {"Y"}, {"D"}
        w[len(w) - 2] = {"N"}
        return w
    if key and key.startswith("MD"):
        w = [set() for _ in range(o[key])]
        w[0] = {"P"}
        if o["MD_B"]:
            w[o["MD_B"]] = {"B"}
        w[len(w) - 2] = {"N"}
        return w
    if op == 0xF4:
        return [set() for _ in range(900)]
    return words(o[key or OPS[op][0]])


E_C_SET = {1: (0,), 2: (0, 1), 3: (1,), 4: (0,)}


def simulate(run, o=DEFAULT, limit=600, log=None):
    """Bus events [(clock, kind, where)] from the end of the first LS, clocks from M0."""
    w = run["chain"]["waits"]
    cyc = 3 + w
    code = bytes.fromhex(run["code_hex"])
    base = 0x10000
    b = read.body_addr(run)
    pc = b - base                       # offset in code of the next byte to pop
    count = 7 if b & 1 else 6           # bytes held beyond the SHL
    pfp = pc + count                    # next byte to fetch (None: flushed, target pending)
    t = o["TE"] + o["TE_W"] * w - 1     # the first SHL's NXT clock
    ev = []
    stg = None                          # staged opcode (its offset) or None
    stg_t = -9                          # the clock of its pop
    rt, ip = [set(), {"N"}, set()], 1   # the SHL's tail: NXT, then the E word
    cur_op, cur_at = 0xD3, None
    cur_key = ""
    regs = run["chain"].get("regs", {})
    cl, dw = 31, regs.get("DW", 0x20)   # CL and DW as the program sets them
    e_n = 0                             # boundaries so far
    e_clock = -9                        # the clock of the latest boundary
    after_flush = False
    delivered = 99                      # bytes delivered since the latest flush
    f_end = None                        # last pin clock of the latest fetch
    f_bytes = 0
    flush_due = flush_to = None
    eu_due = eu_kind = eu_where = None  # the EU's request: earliest clock of its cycle
    eu_end = None                       # last pin clock of the EU's cycle
    eu_hold = False                     # an I/O write posted, its routine not yet ended
    req_clock = -9                      # the clock of the latest request word
    pend = False                        # a fetch is wanted while an EU cycle holds the bus
    skipped = False                     # that fetch gave way to a boundary on the last clock
    ch_start = 0
    y_clock = -9
    f_chx = 0                       # (round 21) the latest fetch is in a chain behind an EU cycle
    f_lag = False                       # the latest fetch's slot is ahead of its pin cycle
    next_lag = False                    # ... and another fetch is chained behind it
    halted = False
    halt_pop = None
    calls = []                          # return offsets of the near calls made
    bw = vec3 = 0
    m16 = {}                            # words stored by MOV [d16],imm16 (vectors, pointers)
    unarmed, armed_t = False, None      # the posted write still waits for its datum (K)
    aw, bw = 0, regs.get("BW", 0x0800)  # AW after the long shift; BW
    last_first, last_first_ip = -9, None
    waited = None
    cn_t = c_wait = None
    after_w, last_kind = None, ""       # the fetch right behind an EU cycle: its last clock
    for i_ in run["chain"]["instrs"]:   # (round 12) MOV BL,imm8 set up before M0
        if i_["role"] == "ls":
            break
        if i_["code"][:2].lower() == "b3":
            bw = (bw & 0xFF00) | int(i_["code"][2:4], 16)
        c_ = bytes.fromhex(i_["code"])
        if c_[0] == 0xBB:
            bw = c_[1] | c_[2] << 8
        if c_[:2] == b"\xc7\x06":
            m16[c_[2] | c_[3] << 8] = c_[4] | c_[5] << 8
            if (c_[2] | c_[3] << 8) == 0x0C:
                vec3 = c_[4] | c_[5] << 8
    hist = {}                           # the count at each clock's end (before a delivery)
    of_stage = False                    # (round 16) the 0F byte has run: its second byte is staged
    rep_op = 0
    rep = False                         # a REP prefix precedes the instruction
    cw = 31                             # CW as the long shift's MOV CL,31 leaves it
    zf = True                           # Z as the long shift leaves it (JZ taken, JNZ not)
    forced = 0
    lag = o["S_LAG"]
    while t < limit:
        in_fetch = f_end is not None and t <= f_end
        last_clock = f_end is not None and t == f_end
        eu_run = eu_end is not None and t <= eu_end
        after_eu = eu_end is not None and t == eu_end + 1
        just_ended = f_end is not None and t == f_end + 1
        # ---- the EU's word
        acts = rt[ip]
        vw = "V" in acts           # (round 10) V: a memory request (Y) honoured only on a
        if vw:                     # running fetch's last clock (one later than Y)
            acts = (set(acts) - {"V"}) | {"Y"}
        cw_ = "C" in acts          # (round 10) C: a bus-idle word (B) that also waits on the
        if cw_:                    # clock a back-to-back fetch starts (the commit word, Q24)
            acts = (set(acts) - {"C"}) | {"B"}
        iw = "I" in acts or (o["P2_Q"] == 2 and "P2" in acts and "B" in acts)   # (round 21) P2_Q=2: every bus-idle word-wide pop
        iw_ = "I" in acts           # (round 20) I: a bus-idle word (B) that also waits on the
        if iw:                     # clock any back-to-back fetch starts, with no exemption
            acts = (set(acts) - {"I"}) | {"B"}   # (LEA with d16 / direct: the release word)
        lw = "L" in acts           # (round 14) L: a bus-idle word that passes from a fetch's
        if lw:                     # second-last clock on (the bus unit's "idle next" level)
            acts = (set(acts) - {"L"}) | {"B"}
        uw = "U" in acts           # (round 11) U: a routine's second request, like Z, that
        if uw:                     # is a read (CMPBK's second operand)
            acts = (set(acts) - {"U"}) | {"Y"}
        zw = "Z" in acts           # (round 8) Z: a memory write request (Y) of a routine whose
        if zw:                     # first cycle is a read (read-modify-write)
            acts = (set(acts) - {"Z"}) | {"Y"}
        is_last = ip == len(rt) - 1
        npop = ("P" in acts) + ("P2" in acts)
        stall = lead_pri = False
        # the setup slot of the fetch in flight or about to start (S_LAG): `first` its first clock
        bus_idle = not in_fetch and not eu_run and not (eu_due is not None and t >= eu_due)
        slot, first = in_fetch, False
        if lag and in_fetch and f_lag:
            if t <= f_end - lag:
                slot = True
            elif t == f_end - lag + 1:
                slot = first = pfp is not None and count + f_bytes <= o["B2B_AT"]
            else:
                slot = next_lag
        elif lag and not in_fetch and pend and pfp is not None and count <= o["IDLE_AT"]:
            slot = (eu_run and t >= eu_end - lag + 1) or (bus_idle and (after_eu or skipped))
            first = eu_run and t == eu_end - lag + 1
        elif (lag and not in_fetch and f_lag and next_lag and bus_idle and f_end is not None
              and t == f_end + 1 and pfp is not None and count <= o["B2B_AT"]):
            slot = True
        # the EU cycle's own slot: its pin cycle moved S_LAG clocks earlier (EU_SLOT)
        eu_slot = bool(o["EU_SLOT"]) and (
            (eu_due is not None and not eu_hold and t >= eu_due - lag)
            or (eu_run and t <= eu_end - lag))
        if "T" in acts and in_fetch and t - (f_end - cyc + 1) < o["T_N"]:
            stall = True            # (round 12) T: waits through a fetch's first T_N clocks
        for act in "XSABFY":
            if act not in acts:
                continue
            kind = o["Y_MODE"] if act == "Y" else "slot" if act in o["LAG_ACTS"] else "pin"
            if kind == "slot":
                busy = (slot and not (first and act in o["LAG_FIRST"])) or eu_slot
            elif kind == "late":
                busy = in_fetch and f_end - t >= (1 if vw else o["Y_LEFT"])
                if vw and o["V_LAG"] and in_fetch and f_lag and lag:
                    # (round 21, trial) V behind an EU cycle's fetch chain waits by the slot:
                    # honoured on the slot's last clock (the pin cycle's, S_LAG clocks earlier)
                    busy = (t != f_end - lag) if o["V_LAG"] == 1 else (t > f_end - lag)
            elif kind == "pin":
                busy = in_fetch and (act not in o["B_ACTS"] or t >= f_end - cyc + o["B_FROM"])
                if act == "B" and lw:
                    busy = (in_fetch and f_end - t >= 2) or (
                        just_ended and not eu_run and pfp is not None
                        and not (eu_due is not None and t >= eu_due) and count <= o["B2B_AT"])
                # (round 10) B_EU: a bus-idle word also waits while an EU cycle of these kinds
                # is on the pins (the bus unit is not idle whatever the cycle is)
                if act == "B" and eu_run and eu_kind in o["B_EU"] and not (
                        t == eu_end and eu_kind in o["B_EU_LAST"] and (o["B_EU_OF"] == 0 or cur_op == 0x0F)):
                    busy = True     # (round 20) B_EU_LAST: ... except on that cycle's last clock
                # (round 10) B_B2B: nor is the bus idle on the clock a back-to-back fetch
                # starts (the same condition that holds a boundary, Q8)
                if (act == "B" and (o["B_B2B"] or cw_) and just_ended and not eu_run and pfp is not None
                        and not (eu_due is not None and t >= eu_due) and count <= o["B2B_AT"]
                        and not (o["C_NOCH"] and after_w is not None and f_end == after_w
                                 and (o["C_NOCH"] == 1 or (o["C_NOCH"] == 2 and waited == (cur_at, ip)) or (o["C_NOCH"] == 3 and npop)))
                        and not (o["C_NOCH"] == 4 and npop)):
                    busy = True     # (round 14) C_NOCH: not for the fetch chained behind an
                    #                 EU cycle's fetch (Q42's fetch): the commit word passes
                if (act == "B" and iw and just_ended and not eu_run and pfp is not None
                        and not (eu_due is not None and t >= eu_due) and count <= o["B2B_AT"]):
                    busy = True
                # (round 16) B_CH: a bus-idle word does wait on the clock the fetch chained
                # behind an EU cycle's fetch starts (that fetch's slot was taken two clocks
                # ahead of the pins, S_LAG: the word comes too late to stop it); kinds CH_K
                if (act == "B" and o["B_CH"] and just_ended and not eu_run and pfp is not None
                        and after_w is not None and f_end == after_w and last_kind in o["CH_K"]
                        and not (eu_due is not None and t >= eu_due)
                        and count <= o["B2B_AT"] and cyc >= 3 + o["B_CH_W"]):
                    busy = True
            else:
                busy = False
            stall = stall or busy
        # (round 21, trial) P2_Q: any word that pops a word-wide operand waits on the clock a
        # back-to-back fetch starts (a property of the queue's 16-bit read, not of the B word)
        if (o["P2_Q"] and "P2" in acts and just_ended and not eu_run and pfp is not None
                and not (eu_due is not None and t >= eu_due) and count <= o["B2B_AT"]):
            stall = True
        if acts & set("XSABFY"):
            # measurement hook (not a rule): FORCE = (instruction number, word, n) makes that
            # word's bus wait exactly n clocks; DBG collects (instruction, word, clock, waited)
            fo = o.get("FORCE")
            if fo and fo[0] == e_n and fo[1] == ip:
                stall = forced < fo[2]
                forced += 1
            if o.get("DBG") is not None:
                o["DBG"].append((e_n, ip, t, stall, cur_op))
        if "H" in acts:
            # (round 16) H: a word that waits as a boundary does: not while a fetch's pin cycle
            # is in flight, except on its last clock; nor (H_B2B) on the clock a back-to-back
            # fetch would start with four or fewer held
            if in_fetch and not last_clock:
                stall = True
            elif (o["H_B2B"] and just_ended and not eu_run and pfp is not None
                  and not (eu_due is not None and t >= eu_due) and count <= o["IDLE_AT"]):
                stall = True
            elif o["H_EU"] and eu_run and t != eu_end:
                stall = True
        if "D" in acts and (eu_due is not None or eu_run):
            stall = True
        if count < npop + ("N" in acts):
            stall = True
        if "G" in acts:
            # rival: the word completes on the clock before the EU's cycle starts
            f_now = (not in_fetch and not eu_run and pfp is not None and flush_due is None
                     and not (eu_due is not None and t >= eu_due)
                     and count <= o["IDLE_AT"])
            if (eu_due is None or eu_due > t + 1 or f_now
                    or (f_end is not None and f_end > t) or (eu_run and eu_end > t)):
                stall = True
        if is_last and not stall:
            # would a back-to-back fetch start this clock without this word's pops?
            b2b_now = (just_ended and not eu_run and pfp is not None
                       and not (eu_due is not None and t >= eu_due) and count <= o["IDLE_AT"])
            sstg = stg - 1 if (of_stage and stg is not None) else stg
            led = stg is not None and not of_stage and code[stg] in LEADS
            lead_t = stg_t + o[LEADS[code[stg]]] if led else None
            if of_stage and stg is not None and code[stg] in OF_LEAD2:
                led, lead_t = True, stg_t + o["LEAD_0F"]
            if stg is None and "N" not in acts:
                stall = True
            elif b2b_now and o["LEAD_EPRI"] and led and t == lead_t:
                lead_pri = True          # the boundary executes; the fetch gives way a clock
            elif (b2b_now and o["CH_EPRI"] and after_w is not None and f_end == after_w
                  and last_kind in o["CH_K"] and stg is not None and count >= o["EMIN"]
                  and not (info(code, sstg)[2] and count < o["EMIN_M"])
                  and last_first != t - 1):
                # (round 13) CH_EPRI: the fetch that would be chained to the fetch right behind
                # an EU cycle gives way to a boundary on its clock (EU_EPRI one fetch further)
                lead_pri = True
            elif (o["E_C"] and in_fetch and not b2b_now and cn_t is not None
                  and t == f_end - 1 and f_end - cyc + 1 - cn_t in E_C_SET[o["E_C"]]):
                pass                 # (round 14) E_C: behind a commit word the boundary goes on
                #                      the second-last clock of the fetch that word started with
            elif b2b_now or (in_fetch and not last_clock):
                stall = True
            elif o["E_EU"] and eu_run and (t != eu_end or o["E_EU"] == 2
                                              or (led and o["LEAD_EU_END"] and eu_kind in "WR")):
                stall = True
            elif o["E_PEND"] and eu_due is not None and eu_kind in "WR":
                stall = True
            elif after_flush and delivered < o["FIRST_MIN"]:
                stall = True
            elif (stg is not None and info(code, sstg)[0] in ("JR", "CALLR")
                  and count < o["EMIN_J"]):     # (round 12) JMP / CALL r16: four bytes held
                stall = True
            elif (stg is not None and o["EMIN_K"] and info(code, sstg)[0] in o["EMIN_KEYS"].split(",")
                  and count < o["EMIN_K"]):
                stall = True    # (round 16, tested, not kept by default) a per-form byte count
            elif stg is not None and of_stage and count < o["OF_EMIN"]:
                stall = True
            elif stg is not None and not of_stage and info(code, sstg)[2] and count < o["EMIN_M"]:
                stall = True
            elif stg is not None and not of_stage and count < o["EMIN"]:
                stall = True
            elif led and t < lead_t:
                stall = True
        if is_last and stall and last_first_ip != (cur_at, ip):
            last_first, last_first_ip = t, (cur_at, ip)     # the last word's first (stalled) clock
        if is_last and stall:
            last_first = t
        waited = (cur_at, ip) if stall else None      # this word stalled on this clock
        if o.get("WLOG") is not None:      # (round 19) every clock: the word, its acts, stalled or not
            o["WLOG"].append((t, cur_at, ip, "".join(sorted(acts)), stall, is_last))
        if cw_ and "N" in acts and not stall:
            # (round 14) the clock a commit word that had waited released the next opcode
            cn_t = t if (c_wait == (cur_at, ip) or o["E_C"] >= 4) else None
        if cw_ and stall:
            c_wait = (cur_at, ip)
        pops = 0
        if not stall:
            pops = npop
            pc += npop
            if "N" in acts:
                stg = pc
                stg_t = t
                if o.get("NLOG") is not None:       # (round 12) the staging pops, for itab.py
                    o["NLOG"].append((t, pc + base - b))
                if code[pc] == 0xF4 and o["HALT_STOP"]:
                    halted = True
                if code[pc] == 0xF4 and o["HALT_HOLD"]:
                    halt_pop = t
                pc += 1
                pops += 1
            if "Q" in acts:              # (round 8) Q: a word the bus unit sees as a request (no cycle)
                req_clock = t
            if "K" in acts:              # (round 11) K: the write's datum is taken here
                armed_t = t
            if "X" in acts or "Y" in acts:
                unarmed = any("K" in x for x in rt[ip:])
                armed_t = t if "K" in acts else None
                y_clock = t
                if not (vw and o["V_NOPRI"]):
                    req_clock = t
                eu_due = t + (o["Z_LAT"] if (zw or uw) else o["POST_LAT"])
                eu_kind = "W" if zw else "R" if uw else info(code, cur_at)[1]
                eu_hold = bool(o["EU_HOLD"]) and eu_kind == "O"
                if o["YP_UN"] and eu_kind == "R" and ((("P" in acts or o["YP_UN"] > 1) and "B" in acts)
                                                      or cur_key in o["RSV_KEYS"].split(",")):
                    # (round 17, experimental) a read whose request word also releases the
                    # displacement: Q33's table for the unarmed write holds for it too
                    unarmed, armed_t = True, eu_due
                eu_where = (dw if cur_op in (0xEE, 0xEF)
                            else code[cur_at + 1] if cur_op in (0xE6, 0xE7) else None)
                if cur_op in (0x6E, 0x6F) and "X" in acts:      # (round 11) OUTM's port cycle
                    eu_kind, eu_where, eu_hold = "O", dw, False
            if "F" in acts:
                if cur_op in (0xE9, 0xE8):                  # near: a 16-bit displacement
                    d = code[pc - 2] | code[pc - 1] << 8
                    flush_to = pc + d - (65536 if d >= 32768 else 0)
                    if cur_op == 0xE8:
                        calls.append(pc)
                elif cur_op in (0xEA, 0x9A):                # far: offset : segment (1000h here)
                    flush_to = code[pc - 4] | code[pc - 3] << 8
                    if cur_op == 0x9A:
                        calls.append(pc)
                elif cur_op in (0xC3, 0xCB, 0xC2):          # (round 8) the offset last pushed
                    flush_to = calls.pop()
                elif cur_op == 0xCF:                        # (round 13) RETI: the third push back
                    flush_to = calls[-1]
                elif cur_op == 0xFF and code[cur_at + 1] in (0x17, 0x27, 0x1F, 0x2F):   # (round 21) through [BW]
                    flush_to = m16["bw"]
                elif cur_op == 0xFF and code[cur_at + 1] < 0xC0:    # (round 12) CALL / JMP mem
                    flush_to = m16[code[cur_at + 2] | code[cur_at + 3] << 8]
                elif cur_op == 0xCD:                        # (round 12) BRK imm8: its vector
                    flush_to = m16[4 * code[cur_at + 1]]
                elif cur_op == 0xFF:                        # JMP BW: BW loaded by MOV BW,imm16
                    flush_to = bw
                elif cur_op == 0xCC:                        # INT 3: the vector stored at 000Ch
                    flush_to = vec3
                else:
                    d = code[pc - 1]
                    flush_to = pc + d - (256 if d >= 128 else 0)
                flush_due = t + o["FLUSH_LAT"]
                # (round 8) FLUSH_B2B: a back-to-back fetch of the old stream that starts on the
                # flush word's own clock is still made (its word discarded), and the target's
                # fetch then starts no sooner than FLUSH_GAP clocks after its end
                if (o["FLUSH_B2B"] and just_ended and not eu_run and pfp is not None
                        and count - pops <= o["B2B_AT"]):
                    ev.append((t, "F", base + pfp - b))
                    f_end = t + cyc - 1
                    f_bytes = 0
                    flush_due = max(flush_due, f_end + 1 + o["FLUSH_GAP"])
                count = pops = 0
                stg = None
                pc = flush_to
                pfp = None
                delivered = 0
                after_flush = True
            if is_last:
                if eu_hold:              # the routine has ended: its I/O cycle on the next clock
                    eu_due = max(eu_due, t + 1)
                    eu_hold = False
                e_clock = t
                e_n += 1
                second = of_stage
                if second:               # (round 16) the 0F page's own boundary: back to the 0F byte
                    stg -= 1
                of_stage = False
                cur_op, cur_at = code[stg], stg
                if o.get("BLOG") is not None:       # (round 18) the boundaries: (clock of the
                    o["BLOG"].append((t, stg + base - b))   # predecessor's last word, instruction)
                first0f = bool(o["OF2"]) and cur_op == 0x0F and not second
                if log is not None:
                    log.append((t, f"E{e_n} {cur_op:02X}@{stg + base - b:+d} c={count - pops}"
                                   f"{'L' if last_clock else 'f' if in_fetch else 'i'}"))
                if cur_op == 0xF4:
                    limit = t + 8
                if cur_op == 0xB1:
                    cl = code[stg + 1]
                    cw = (cw & 0xFF00) | cl
                if cur_op == 0xB9:
                    cw = code[stg + 1] | code[stg + 2] << 8
                    cl = cw & 0xFF
                if cur_op == 0xBA:
                    dw = code[stg + 1] | code[stg + 2] << 8
                key = info(code, stg)[0]
                if cur_op in (0x42, 0x43, 0x4A, 0x4B):
                    zf = False           # INC / DEC r16 of a register that does not reach zero
                if cur_op in (0x74, 0x75) and not zf:
                    key = "JNZ" if cur_op == 0x74 else "JZ"     # the other outcome's routine
                if cur_op == 0xE3 and cw == 0:      # (round 10) BCWZ taken
                    key = "JCXZT"
                if cur_op == 0xE2:       # (round 10) DBNZ: CW counts down; not taken at zero
                    cw = (cw - 1) & 0xFFFF
                    if cw == 0:
                        key = "LOOPN"
                if cur_op in (0xE0, 0xE1):      # (round 13) DBNZNE / DBNZE: count and Z
                    cw = (cw - 1) & 0xFFFF
                    flag = zf if cur_op == 0xE1 else not zf
                    if cw == 0:
                        key = "LOOPZ0" if flag else "LOOPZ00"
                    elif not flag:
                        key = "LOOPZF"
                    else:
                        key = "LOOPZ"
                if cur_op == 0x3B and code[stg + 1] in (0xC0, 0xDB, 0xC9, 0xD2):
                    zf = True                   # CMP r,r of a register with itself
                if cur_op == 0x68:
                    calls.append(code[stg + 1] | code[stg + 2] << 8)
                if cur_op == 0xBB:
                    bw = code[stg + 1] | code[stg + 2] << 8
                if cur_op == 0xC7 and code[stg + 1] == 0x06 and code[stg + 2] == 0x0C:
                    vec3 = code[stg + 4] | code[stg + 5] << 8
                if cur_op == 0xC7 and code[stg + 1] == 0x07:      # (round 21) MOV word [BW],imm16
                    m16["bw"] = code[stg + 2] | code[stg + 3] << 8
                if cur_op == 0xC7 and code[stg + 1] == 0x06:      # MOV word [d16],imm16
                    m16[code[stg + 2] | code[stg + 3] << 8] = code[stg + 4] | code[stg + 5] << 8
                cur_key = key
                rt = routine(cur_op, o, code[stg + 2] & 31 if cur_op in (0xC0, 0xC1) else cl, key)
                # (round 11) operands of the signed multiply / divide: the sign fix-ups are
                # extra words (MD_NEG: the product's or the quotient's; MD_DNEG: a negative
                # dividend's)
                if cur_op == 0xB8:
                    aw = code[stg + 1] | code[stg + 2] << 8
                if cur_op == 0xB0:
                    aw = (aw & 0xFF00) | code[stg + 1]
                if cur_op == 0xB3:
                    bw = (bw & 0xFF00) | code[stg + 1]
                if cur_op == 0xD3 and code[stg + 1] == 0xE0 and cl >= 16:
                    aw = 0
                if key in ("EXT", "INS", "EXTI", "INSI"):
                    # EXT / INS: n bits at bit offset `off` of the word at DS0:IX / DS1:IY. The
                    # offset is the r/m register's low nibble; the length is imm4 + 1 (EXTI /
                    # INSI, round 12) or the reg-field register's low nibble + 1 (round 16: any
                    # 8-bit register, not only AL). The offset register is left at off + n
                    # (round 16), which is what the same instruction twice runs on.
                    m_ = code[stg + 2]
                    r8 = [aw & 255, cl, dw & 255, bw & 255, aw >> 8, cw >> 8, dw >> 8, bw >> 8]
                    immf = key in ("EXTI", "INSI")
                    n = ((code[stg + 3] if immf else r8[(m_ >> 3) & 7]) & 15) + 1
                    off = r8[m_ & 7] & 15
                    ext = key in ("EXT", "EXTI")
                    head = (o["EXT_HEAD"] if ext or not o["INSI_HEAD"] else o["INSI_HEAD"]) if immf else o["EXTR_HEAD"]
                    tailp = o["EXTI_TAIL"] if immf else "N ."
                    # (round 21) the imm4 forms' heads carry words of the body: bases shortened
                    xd = (o["EXTI_D"] if ext else o["INSI_D"]) if immf else 0
                    if off + n <= 16 and ext:
                        # two shift loops of two words a bit, 16 - off - n and 16 - n long, the
                        # second with a four-word entry
                        v = (o["EXT_K"] if n < 16 else 0) + 2 * (16 - off - n) + 2 * (16 - n)
                        rt = (words(head) + [set() for _ in range(o["EXT_BASE" if immf else "EXTR_BASE"] + v - xd)]
                              + words(tailp))
                    elif ext:
                        # (round 13) across the word: a second read, then 2 words per bit of
                        # offset (one more when n < 16)
                        rt = (words(head) + [set() for _ in range(o["EXTX_GAP"] - xd + (0 if immf else o["EXTRX_D"]))]
                              + words("U D")
                              + [set() for _ in range(o["EXTX_BASE"] + 2 * off + (n < 16))]
                              + words(tailp))
                    elif off + n <= 16:
                        # INS inside one word: a fixed length, two words more for a non-zero
                        # offset, eight fewer when the field ends at bit 15
                        v = 2 * (off > 0) - 8 * (off + n == 16)
                        rt = (words(head) + [set() for _ in range(o["INS_BASE" if immf else "INSR_BASE"] + v - xd)]
                              + words("Z G " + tailp))
                    else:
                        mm_ = off + n - 16
                        rt = (words(head) + [set() for _ in range(o["INSX_1"] - xd + (0 if immf else o["INSRX_D"]))]
                              + words("Z D") + [set() for _ in range(o["INSX_GAP"])]
                              + words("U D") + [set() for _ in range(o["INSX_BASE"] + 4 * mm_)]
                              + words("Z G " + tailp))
                    if o["BF_OFF"] and not first0f:
                        no = (off + n) & 15
                        ri = m_ & 7
                        if ri == 3:
                            bw = (bw & 0xFF00) | no
                        elif ri == 2:
                            dw = (dw & 0xFF00) | no
                        elif ri == 0:
                            aw = (aw & 0xFF00) | no
                if key == "PREP" and code[stg + 3] & 31:
                    # (round 12) PREPARE with a nesting level L >= 1: L - 1 frame-pointer
                    # copies (a read and a push each), then the push of the new frame pointer
                    lv = code[stg + 3] & 31
                    rt = (words(o["PREP_HEAD"]) + (lv - 1) * words(o["PREP_COPY"])
                          + words(o["PREP_TAIL"]))
                if key in ("ADD4S", "SUB4S", "CMP4S"):
                    # (round 12) the BCD strings: one iteration per byte (two digits), the
                    # digit count in CL; a head, the iterations, a tail
                    it = max(1, (cl + 1) // 2)
                    kk = "CMP4S" if key == "CMP4S" else "ADD4S"
                    rt = (words(o["H_4S"]) + it * words(o["I_" + kk]) + words(o["T_" + kk]))
                if key in ("MI16", "MI8"):
                    im = (code[stg + 2] | code[stg + 3] << 8) if key == "MI16" else code[stg + 2]
                    si_ = (im >> 15) & 1 if key == "MI16" else (im >> 7) & 1
                    extra = o["MD_MNEG"] * (si_ ^ ((bw >> 15) & 1))
                    rt = rt[:6] + [set() for _ in range(extra)] + rt[6:]
                if key and key.startswith("MD") and key[2] in "57":
                    wide = key[3] == "W"
                    sa = (aw >> 15) & 1 if (wide or key[2] == "7") else (aw >> 7) & 1
                    if key[2] == "7" and wide:
                        sa = (dw >> 15) & 1
                    sb = (bw >> 15) & 1 if wide else (bw >> 7) & 1
                    extra = 0
                    if key[2] == "5":
                        extra = o["MD_MNEG"] * (sa ^ sb)
                    else:
                        extra = o["MD_QNEG"] * (sa ^ sb) + o["MD_DNEG"] * sa
                    rt = rt[:4] + [set() for _ in range(extra)] + rt[4:]
                # (round 11) REP: the prefix is its own two-word routine; the string routine
                # behind it is a head, CW iterations and a tail (or the CW = 0 exit)
                if rep and key in REPS:
                    if cw == 0:
                        rt = words(o["REP_ZERO"])
                    else:
                        left = 0
                        if key == "SCAS" and rep_op in (0xF2, 0x65):
                            # ends at its first element (CW - 1 left, seen in the shift behind
                            left = cw - 1       # it) after a second read
                            cw = o["REP_CMP_N"]
                        elif key == "SCAS":     # (round 13) REPNC: to the count, one read ahead
                            cw += 1
                        if key == "CMPBK" and rep_op in (0xF2, 0x65):
                            left = cw - 1       # REPC / REPNE over equal data: the first pair ends it
                            cw = 1
                        cmp_left = left if key == "CMPBK" else None
                        if key == "CMPBK":      # ends on the count, one element pair read ahead
                            cw += 1
                        rt = (words(o.get("RH_" + key, o["REP_HEAD"]))
                              + (cw - 1) * words(o["RI_" + key])
                              + words(o.get("RL_" + key, o["RI_" + key]))
                              + words(o["RT_" + key]))
                        if key == "SCAS" and rep_op in (0xF3, 0x64):
                            # (round 13) to the count: the first read, then 12-clock iterations
                            rt = (words(o["REP_HEAD"]) + words(o["RI_SCAS"])
                                  + (cw - 1) * words(o["RI_SCAS_C"]) + words(o["RT_SCAS_C"]))
                        if key == "CMPBK" and rep_op in (0xF2, 0x65):
                            rt = rt[:-len(words(o["RT_CMPBK"]))] + words(o["RT_CMPBK_C"])
                        if key == "CMPBK":
                            left = cmp_left or 0
                        cw = left
                    cl = cw & 0xFF
                if first0f:
                    # (round 16) OF2: the 0F byte is a two-word routine of its own that takes the
                    # second byte as an opcode (N); the instruction proper starts at a boundary
                    rt = words(o["OF_PFX"])
                    of_stage = True
                elif second:
                    rt = rt[o["OF_DROP"]:]
                rep = cur_op in (0xF2, 0xF3, 0x64, 0x65)
                rep_op = cur_op
                after_flush = False
                ip = 0
                stg = None
            else:
                ip += 1
        count -= pops
        # ---- the bus unit
        bus_free = not in_fetch and not eu_run
        eu_started = f_started = gave_way = False
        if halt_pop is not None and eu_due is not None and eu_due > halt_pop:
            eu_due += o["HALT_HOLD"]
            halt_pop = None
        # (round 11) ARB: the chained fetch's decision is taken before the pins. A memory
        # request older than three clocks at the fetch's end did not hold that decision: the
        # fetch goes first (when the count allows one) and the EU cycle follows it. A request
        # made three clocks before the pins (the decision's eve) holds it: no chained fetch.
        old_loses = (o["ARB"] & 1 and just_ended and eu_due is not None and eu_kind in o["ARB_K"]
                     and unarmed and (armed_t is None or armed_t > t - 2) and pfp is not None
                     and not halted and hist.get(t - 2, 99) + f_bytes <= o["B2B_AT"])
        # (round 21) LCH: a fetch chained behind an EU cycle's fetch (the lagged chain, S_LAG) is
        # committed at its slot's first clock, S_LAG - 1 clocks before the pins: a memory request
        # that is not ripe before that clock does not stop it (the EU cycle follows the fetch)
        if o.get("DBGL") and o["DBGL"][0] <= t <= o["DBGL"][1]: print(t, "je", just_ended, "flag", f_lag, "nl", next_lag, "due", eu_due, "fend", f_end, "cnt", count, "hold", eu_hold, "pend", pend, "in_f", in_fetch, "req", req_clock)
        if (o["LCH"] and just_ended and f_chx >= o["LCH_MIN"] and last_kind in o["LCH_AFTER"] and eu_due is not None and eu_kind in o["LCH_K"]
                and eu_due >= f_end - o["S_LAG"] + o["LCH"] and pfp is not None and not halted
                and count <= o["B2B_AT"] and not eu_hold and o["LCH"] < 3):
            old_loses = True
        # LCH=3: no arbitration inside the chain: a read requested at or after the clock before
        # the chain's first pin clock (LCH_Y) waits until the chain ends (more than five held)
        if (o["LCH"] == 3 and just_ended and f_chx >= 1 and eu_due is not None and eu_kind in o["LCH_K"]
                and y_clock >= ch_start - o["LCH_Y"] and pfp is not None
                and not halted and count <= o["B2B_AT"] and not eu_hold):
            old_loses = True
        # (round 21) RIPE4: a fetch at four or fewer held beats a read that becomes ripe on this
        # very clock (1: on the fetch chain behind an EU cycle only; 2: after any fetch)
        if (o["RIPE4"] and just_ended and eu_due == t and eu_kind in o["LCH_K"] and pfp is not None
                and not halted and count <= o["IDLE_AT"] and not eu_hold
                and (o["RIPE4"] == 2 or f_chx >= 1)):
            old_loses = True
        if bus_free and eu_due is not None and t >= eu_due and not eu_hold and not old_loses:
            ev.append((t, eu_kind, eu_where))
            eu_end = t + (2 if eu_kind in ("O", "I") else cyc - 1)
            # (round 11) a word at an odd address: two byte cycles back to back, the pair one
            # cycle of twice the length (nothing between them)
            if eu_kind in "RW" and cur_op is not None and (
                    (regs.get("SP", 0) & 1 and (0x50 <= cur_op <= 0x61 or cur_op in STACK_OPS))
                    or (regs.get("BW", 0) & 1 and cur_at is not None and cur_op & 1
                        and cur_op in (0x8B, 0x89, 0x01, 0x03, 0xFF, 0x87, 0x85, 0x3B, 0xC7,
                                       0x81, 0x83, 0xF7, 0xD1)
                        and code[cur_at + 1] < 0xC0 and (code[cur_at + 1] & 7) == 7)):
                ev.append((t + cyc, eu_kind, eu_where))
                eu_end = t + 2 * cyc - 1
            last_kind = eu_kind
            eu_due = None
            eu_started = True
        if bus_free and not eu_started and flush_due is not None and t >= flush_due:
            pfp = flush_to
            flush_due = None
        if bus_free and not eu_started and pfp is not None and not halted:
            lim = o["IDLE_AT"]
            if just_ended and e_clock != t and not (o["REQ_PRI"] and req_clock == t - 1):
                lim = o["B2B_AT"]
            if (o["ARB"] & 2 and just_ended and eu_due is not None and eu_kind in o["ARB_K"]
                    and req_clock == t - 3):
                lim = -1
            # (round 12) LAG_B2B: the fetch chained to the fetch that followed an EU cycle
            # (kinds LAG_K) is made at the idle limit, not at "five held" (Q12 carried one
            # fetch further)
            if (o["LAG_B2B"] and just_ended and after_w is not None and f_end == after_w
                    and lim == o["B2B_AT"]):
                lim = o["IDLE_AT"]
            # (round 13) CH_BNEXT: nor is that chained fetch started when the EU's next word is
            # a bus-idle word (the word would have to wait for the whole fetch)
            if (o["CH_BNEXT"] and just_ended and after_w is not None and f_end == after_w
                    and last_kind in o["CH_K"] and ip < len(rt) and "B" in rt[ip] and not (iw and stall)
                    and not pops):
                lim = -1
            give_way = ((o["EU_EPRI"] and after_eu and pend and e_clock == t)
                        or (lead_pri and e_clock == t))
            if count <= lim and not give_way:
                addr = base + pfp
                f_bytes = 1 if addr & 1 else 2
                ev.append((t, "F", addr - b))
                # the slot stays ahead of the pins for a fetch that was pending under an EU
                # cycle and for one chained to such a fetch (unless a pop falls on this clock)
                if pend:
                    ch_start = t
                f_chx = 1 if pend else (f_chx + 1 if (f_chx and f_end is not None and t == f_end + 1) else 0)
                f_lag = pend or (f_lag and next_lag and f_end is not None and t == f_end + 1
                                 and not (o["CHAIN_POP"] and pops))
                after_w = (t + cyc - 1) if (eu_end is not None and t == eu_end + 1
                                             and last_kind in o["LAG_K"]) else None
                f_end = t + cyc - 1
                pfp += f_bytes
                f_started = True
                if o.get("DBGF") is not None:
                    o["DBGF"][t] = f_lag
            gave_way = give_way and count <= lim
        skipped = gave_way
        if f_end is not None and f_lag and t == f_end - lag + 1 and not f_started:
            # the chained slot's decision, S_LAG clocks ahead of the pins
            next_lag = pfp is not None and count + f_bytes <= o["B2B_AT"]
        if f_started:
            next_lag = False
        if eu_run or eu_started:
            pend = pend or (pfp is not None and count <= o["IDLE_AT"])
        elif not skipped:
            pend = False
        hist[t] = count
        if o.get("HIST") is not None:
            o["HIST"][t] = count
        if f_end is not None and t == f_end:    # delivered at the end of the last clock
            count += f_bytes
            delivered += f_bytes
        t += 1
    return ev


def silicon(run, o=DEFAULT):
    """Silicon's events from the first LS's end, in the model's form."""
    t0 = o["TE"] + o["TE_W"] * run["chain"]["waits"] - 1
    return [(c, k, (wh if k in "FO" else None)) for c, k, wh in read.events(run) if c >= t0]


def compare(run, o=DEFAULT):
    """Silicon's and the model's events from the first LS's end to M1 (inclusive)."""
    si = silicon(run, o)
    mo = simulate(run, o)
    m1 = next(bytes.fromhex(i["code"]) for i in run["chain"]["instrs"] if i["form"] == "M1")
    if m1[0] == 0x50:
        stop = lambda e: e[1] == "W"
    else:
        stop = lambda e: e[1] == "O" and e[2] == 0x20

    def cut(ev):
        out = []
        for e in ev:
            out.append(e)
            if stop(e):
                break
        return out
    return cut(si), cut(mo)


def fmt(ev):
    return " ".join(f"{c}:{format(wh, '+d') if k == 'F' else k}" for c, k, wh in ev)


def options(pairs):
    o = dict(DEFAULT)
    for kv in pairs:
        k, v = kv.split("=", 1)
        o[k] = int(v) if v.lstrip("-").isdigit() else v
    return o


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", nargs="+", dest="ids")
    ap.add_argument("--waits", nargs="+", type=int)
    ap.add_argument("--parity", nargs="+")
    ap.add_argument("--opt", nargs="+", default=[])
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--log", action="store_true")
    args = ap.parse_args(argv)
    o = options(args.opt)
    runs = read.load("socket")
    n = ok = okw = 0
    groups = {}
    for cid, run in read.select(runs, args.ids, args.waits, args.parity):
        try:
            a, m = compare(run, o)
            whole = silicon(run, o) == simulate(run, o)
        except (KeyError, IndexError, TypeError) as exc:
            a, m, whole = [], [(0, "?", repr(exc))], False
        n += 1
        same = a == m
        ok += same
        okw += whole
        g = cid.split("-")[0][2:] + ":" + cid.split("-")[1]
        groups.setdefault(g, [0, 0])
        groups[g][0] += same
        groups[g][1] += 1
        if args.v or (not same and args.ids):
            print(f"{cid:<22} {'=' if same else 'X'}\n   si {fmt(a)}\n   mo {fmt(m)}")
            if args.log:
                log = []
                simulate(run, o, log=log)
                print("   " + " | ".join(f"{t}:{s}" for t, s in log[:14]))
    print(" ".join(f"{g}:{a}/{b}" for g, (a, b) in groups.items()))
    print(f"{ok} / {n} runs: the model's events from the first LS's end to M1 are silicon's; "
          f"{okw} / {n} to the program's end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
