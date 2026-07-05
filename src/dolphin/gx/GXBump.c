/**
 * GXBump.c
 * Description:
 */

#include "dolphin/gx/GXBump.h"
#include "dolphin/gx/GX.h"

void GXSetTevIndirect(GXTevStageID tevStage, GXIndTexStageID texStage, GXIndTexFormat texFmt,
                      GXIndTexBiasSel biasSel, GXIndTexMtxID mtxID, GXIndTexWrap wrapS,
                      GXIndTexWrap wrapT, u8 addPrev, u8 utcLod, GXIndTexAlphaSel alphaSel) {
    u32 field = 0;

    GX_BITFIELD_SET(field, 30, 2, texStage);
    GX_BITFIELD_SET(field, 28, 2, texFmt);
    GX_BITFIELD_SET(field, 25, 3, biasSel);
    GX_BITFIELD_SET(field, 23, 2, alphaSel);
    GX_BITFIELD_SET(field, 19, 4, mtxID);
    GX_BITFIELD_SET(field, 16, 3, wrapS);
    GX_BITFIELD_SET(field, 13, 3, wrapT);
    GX_BITFIELD_SET(field, 12, 1, utcLod);
    GX_BITFIELD_SET(field, 11, 1, addPrev);
    GX_BITFIELD_SET(field, 0, 8, tevStage + 0x10);

    GXFIFO.u8 = 0x61;
    GXFIFO.s32 = field;

    gx->bpSentNot = 0;
}

void GXSetIndTexMtx(GXIndTexMtxID mtxID, f32 offset[6], s8 scale_exp) {
    u32 val;
    u32 field;
    f32 mtx2[6];
    u32 stack_padding[6];

    scale_exp += 17;

    switch (mtxID) {
    case GX_ITM_0:
    case GX_ITM_1:
    case GX_ITM_2:
        val = mtxID - 1;
        break;
    case GX_ITM_S0:
    case GX_ITM_S1:
    case GX_ITM_S2:
        val = mtxID - 5;
        break;
    case GX_ITM_T0:
    case GX_ITM_T1:
    case GX_ITM_T2:
        val = mtxID - 9;
        break;
    case GX_ITM_3:
    case GX_ITM_S3:
    default:
        val = 0;
    }

    field = 0;
    GX_BITFIELD_SET(field, 21, 11, 1024.0f * offset[0]);
    GX_BITFIELD_SET(field, 10, 11, 1024.0f * offset[3]);
    GX_BITFIELD_SET(field, 8, 2, (scale_exp >> 0) & 3);
    GX_BITFIELD_SET(field, 0, 8, val * 3 + 6);
    GXFIFO.u8 = 0x61;
    GXFIFO.s32 = field;

    field = 0;
    GX_BITFIELD_SET(field, 21, 11, 1024.0f * offset[1]);
    GX_BITFIELD_SET(field, 10, 11, 1024.0f * offset[4]);
    GX_BITFIELD_SET(field, 8, 2, (scale_exp >> 2) & 3);
    GX_BITFIELD_SET(field, 0, 8, val * 3 + 7);
    GXFIFO.u8 = 0x61;
    GXFIFO.s32 = field;

    field = 0;
    GX_BITFIELD_SET(field, 21, 11, 1024.0f * offset[2]);
    GX_BITFIELD_SET(field, 10, 11, 1024.0f * offset[5]);
    GX_BITFIELD_SET(field, 8, 2, (scale_exp >> 4) & 3);
    GX_BITFIELD_SET(field, 0, 8, val * 3 + 8);
    GXFIFO.u8 = 0x61;
    GXFIFO.s32 = field;

    gx->bpSentNot = 0;
}

void GXSetIndTexCoordScale(GXIndTexStageID texStage, GXIndTexScale scaleS, GXIndTexScale scaleT) {
    GXData* data;

    switch (texStage) {
    case GX_INDTEXSTAGE0:
        data = gx;
        GX_BITFIELD_SET(data->IndTexScale0, 28, 4, scaleS);
        GX_BITFIELD_SET(data->IndTexScale0, 24, 4, scaleT);
        GX_BITFIELD_SET(data->IndTexScale0, 0, 8, 0x25);
        GXFIFO.u8 = 0x61;
        GXFIFO.s32 = data->IndTexScale0;
        break;
    case GX_INDTEXSTAGE1:
        data = gx;
        GX_BITFIELD_SET(data->IndTexScale0, 20, 4, scaleS);
        GX_BITFIELD_SET(data->IndTexScale0, 16, 4, scaleT);
        GX_BITFIELD_SET(data->IndTexScale0, 0, 8, 0x25);
        GXFIFO.u8 = 0x61;
        GXFIFO.s32 = data->IndTexScale0;
        break;
    case GX_INDTEXSTAGE2:
        data = gx;
        GX_BITFIELD_SET(data->IndTexScale1, 28, 4, scaleS);
        GX_BITFIELD_SET(data->IndTexScale1, 24, 4, scaleT);
        GX_BITFIELD_SET(data->IndTexScale1, 0, 8, 0x26);
        GXFIFO.u8 = 0x61;
        GXFIFO.s32 = data->IndTexScale1;
        break;
    case GX_INDTEXSTAGE3:
        data = gx;
        GX_BITFIELD_SET(data->IndTexScale1, 20, 4, scaleS);
        GX_BITFIELD_SET(data->IndTexScale1, 16, 4, scaleT);
        GX_BITFIELD_SET(data->IndTexScale1, 0, 8, 0x26);
        GXFIFO.u8 = 0x61;
        GXFIFO.s32 = data->IndTexScale1;
        break;
    }

    gx->bpSentNot = 0;
}

void GXSetIndTexOrder(GXIndTexStageID stage, GXTexCoordID coord, GXTexMapID map) {
    switch (stage) {
    case GX_INDTEXSTAGE0:
        GX_BITFIELD_SET(gx->iref, 29, 3, map);
        GX_BITFIELD_SET(gx->iref, 26, 3, coord);
        break;
    case GX_INDTEXSTAGE1:
        GX_BITFIELD_SET(gx->iref, 23, 3, map);
        GX_BITFIELD_SET(gx->iref, 20, 3, coord);
        break;
    case GX_INDTEXSTAGE2:
        GX_BITFIELD_SET(gx->iref, 17, 3, map);
        GX_BITFIELD_SET(gx->iref, 14, 3, coord);
        break;
    case GX_INDTEXSTAGE3:
        GX_BITFIELD_SET(gx->iref, 11, 3, map);
        GX_BITFIELD_SET(gx->iref, 8, 3, coord);
        break;
    }

    GXFIFO.u8 = 0x61;
    GXFIFO.s32 = gx->iref;
    GXSetWasteFlags();
}

void GXSetNumIndStages(u8 num) {
    GXData* data = gx;
    GX_BITFIELD_SET(data->genMode, 13, 3, num);
    data->dirtyState |= GX_DIRTY_BP_MASK | GX_DIRTY_GEN_MODE;
}

#pragma dont_inline on
void GXSetTevDirect(GXTevStageID stage) {
    GXSetTevIndirect(stage, GX_INDTEXSTAGE0, GX_ITF_8, GX_ITB_NONE, GX_ITM_OFF, GX_ITW_OFF,
                     GX_ITW_OFF, FALSE, FALSE, GX_ITBA_OFF);
}

void GXSetTevIndWarp(GXTevStageID tevStage, GXIndTexStageID indStage, GXBool signedOffsets,
                     GXBool replaceSummands, GXIndTexMtxID matSel) {
    GXIndTexWrap wrap = replaceSummands ? GX_ITW_0 : GX_ITW_OFF;

    GXSetTevIndirect(tevStage, indStage, GX_ITF_8, signedOffsets ? GX_ITB_STU : GX_ITB_NONE,
                     matSel, wrap, wrap, FALSE, FALSE, GX_ITBA_OFF);
}
#pragma dont_inline reset

void __GXUpdateBPMask(void) {
    GXData* data = gx;
    u32 i;
    u32 map;
    u32 newImask = 0;
    u32 nStages = GX_GET_REG(data->genMode, 13, 15);
    u32* pBpMask;
    u32 reg;

    for (i = 0; i < nStages; i++) {
        switch (i) {
        case 0:
            map = data->iref & 7;
            break;
        case 1:
            map = GX_GET_REG(data->iref, 23, 25);
            break;
        case 2:
            map = GX_GET_REG(data->iref, 17, 19);
            break;
        case 3:
            map = GX_GET_REG(data->iref, 11, 13);
            break;
        }
        newImask |= 1 << map;
    }

    pBpMask = &data->bpMask;
    reg = data->bpMask;
    if ((u8)reg != newImask) {
        *pBpMask = (reg & ~0xFF) | newImask;
        GXFIFO.u8 = 0x61;
        GXFIFO.u32 = gx->bpMask;
        gx->bpSentNot = 0;
    }
}

void __GXSetIndirectMask(u32 mask) {
    GXData* data = gx;

    GX_BITFIELD_SET(data->bpMask, 24, 8, mask);
    GXFIFO.u8 = 0x61;
    GXFIFO.s32 = data->bpMask;
    data->bpSentNot = 0;
}

void __GXFlushTextureState(void) {
    GXFIFO.u8 = 0x61;
    GXFIFO.s32 = gx->bpMask;
    gx->bpSentNot = 0;
}
