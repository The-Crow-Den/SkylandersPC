// SPDX-License-Identifier: GPL-2.0-or-later
// renderer: the frame statistics report (SKY_RENDERER_FRAME_STATS), taken at each flip.
#pragma once

namespace SkyVideoOut {
bool FrameStatsEnabled();
void OnFlipStats();
} // namespace SkyVideoOut
