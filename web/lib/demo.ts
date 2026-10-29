// Demonstration data. These findings describe the synthetic clip at
// public/demo/demo-procedure.webm (made by scripts/make_demo_video.py) and
// must NEVER be shown on top of a user's own upload.

import type { AnalysisResult, Finding, ReportMoment, ReviewReport, SessionDetails } from "./types";

export const DEMO_VIDEO_SRC = "/demo/demo-procedure.webm";

export const DEMO_SESSION_ID = "demo-session";

// A real recording that "Analyze demo video" uploads to the backend like any other video:
// three minutes of MM-OR test surgery 038 (public/demo/README.md; MM-OR's terms of use apply).
export const SAMPLE_VIDEO_SRC = "/demo/mmor-038-demo.mp4";

export const SAMPLE_DETAILS: SessionDetails = {
  name: "Demo: MM-OR knee replacement (surgery 038)",
  procedureContext:
    "Three minutes of a simulated robot-assisted knee replacement from the MM-OR dataset, one angled ceiling camera at 1 frame per second. The drape, instrument table and instruments are sterile; the operating table sides, anesthesia equipment and other undraped equipment are nonsterile.",
  acknowledged: true,
};

export const DEMO_DETAILS: SessionDetails = {
  name: "Demonstration: synthetic practice station",
  // The sterile/nonsterile labels in the demo findings come from this context and
  // from the labels drawn in the synthetic clip, not from how things look.
  procedureContext:
    "Simulated sterile-field exercise drawn with labelled shapes; no real people or patients. Per this exercise's protocol, the drape, instrument tray, forceps, and both gloves are sterile; the side table, face/mask zone, and anything below the table edge are nonsterile.",
  acknowledged: true,
};

export const DEMO_RESULT: AnalysisResult = {
  sessionId: DEMO_SESSION_ID,
  source: "demo",
  createdAt: "2026-10-17T00:00:00.000Z",
  findings: [
    {
      sessionId: DEMO_SESSION_ID,
      eventId: "demo-1",
      timestampSec: 10.5,
      endSec: 16,
      title: "Glove touches side table, then forceps",
      objects: ["Side table", "Right glove", "Forceps"],
      description:
        "The right glove moves onto the designated nonsterile side table, then returns and handles the forceps on the instrument tray.",
      reasonForReview:
        "A sterile glove appears to contact a designated nonsterile surface before touching a sterile instrument, with no glove change in between.",
      evidence: [
        {
          label: "Side table",
          designation: "nonsterile",
          timestampSec: 11,
          observation: "Right glove rests inside the side-table area.",
        },
        {
          label: "Right glove",
          designation: "sterile",
          timestampSec: 12.5,
          observation: "Glove leaves the side table and crosses the drape.",
        },
        {
          label: "Forceps",
          designation: "sterile",
          timestampSec: 15.5,
          observation: "Right glove covers the forceps on the tray.",
        },
      ],
      uncertainty: {
        level: "low",
        notes: "Both contacts are in clear view from this angle.",
      },
      reviewStatus: "needs_review",
    },
    {
      sessionId: DEMO_SESSION_ID,
      eventId: "demo-2",
      timestampSec: 22,
      endSec: 27,
      title: "Glove near the face / mask zone",
      objects: ["Right glove", "Face / mask zone"],
      description:
        "The right glove rises toward the face/mask zone and overlaps its lower edge in the image for about two seconds.",
      reasonForReview:
        "If the glove touched the mask, it would no longer be sterile. The overlap could also be the glove passing in front of the mask.",
      evidence: [
        {
          label: "Right glove",
          designation: "sterile",
          timestampSec: 22,
          observation: "Glove lifts off the drape toward the mask zone.",
        },
        {
          label: "Face / mask zone",
          designation: "nonsterile",
          timestampSec: 24,
          observation: "Glove overlaps the lower edge of the mask zone in the image.",
        },
      ],
      uncertainty: {
        level: "high",
        notes:
          "A single overhead camera cannot show depth. The glove may be hovering in front of the mask rather than touching it.",
      },
      reviewStatus: "needs_review",
    },
    {
      sessionId: DEMO_SESSION_ID,
      eventId: "demo-3",
      timestampSec: 31,
      endSec: 37,
      title: "Glove drops below table edge, then touches drape",
      objects: ["Left glove", "Below table edge", "Sterile drape"],
      description:
        "The left glove moves below the table-edge line, pauses, then returns to the sterile drape.",
      reasonForReview:
        "This exercise's protocol treats anything below the table edge as nonsterile. Hands should stay above that level.",
      evidence: [
        {
          label: "Below table edge",
          designation: "nonsterile",
          timestampSec: 33,
          observation: "Left glove is below the table-edge line.",
        },
        {
          label: "Sterile drape",
          designation: "sterile",
          timestampSec: 36,
          observation: "Left glove is back on the drape.",
        },
      ],
      uncertainty: {
        level: "medium",
        notes:
          "The table-edge line stands in for waist level. Whether the glove touched anything below it is not visible.",
      },
      reviewStatus: "needs_review",
    },
    {
      sessionId: DEMO_SESSION_ID,
      eventId: "demo-4",
      timestampSec: 42.5,
      endSec: 49,
      title: "Forceps out of view, then returned to tray",
      objects: ["Forceps", "Right glove", "Instrument tray"],
      description:
        "The forceps are carried off the tray and out of frame while the view is blocked, then placed back on the tray.",
      reasonForReview:
        "What the forceps contacted while out of view is unknown. A reviewer should decide whether they need to be replaced.",
      evidence: [
        {
          label: "Forceps",
          designation: "sterile",
          timestampSec: 43,
          observation: "Forceps lifted from the tray.",
        },
        {
          label: "View blocked",
          designation: "unknown",
          timestampSec: 45,
          observation: "Camera view is blocked; forceps leave the frame.",
        },
        {
          label: "Instrument tray",
          designation: "sterile",
          timestampSec: 48,
          observation: "Forceps placed back on the tray.",
        },
      ],
      uncertainty: {
        level: "high",
        notes: "The camera view is blocked from 43s to 48s. No contact can be confirmed or ruled out.",
      },
      reviewStatus: "needs_review",
    },
  ],
};

// Sample final report for the demonstration. Hand-written, NOT generated by Gemini, and
// labeled as such in the interface. Times, titles and statuses are read from the findings
// on the page, so they always match what the reviewer sees.
const DEMO_REPORT_TEXT: Record<string, { summary: string; teachingPoint: string }> = {
  "demo-1": {
    summary:
      "The right glove rested on the nonsterile side table, then handled the forceps on the instrument tray about four seconds later without a glove change.",
    teachingPoint: "After any contact with a nonsterile surface, stop and change gloves before touching the sterile field.",
  },
  "demo-2": {
    summary:
      "The right glove rose toward the face and mask zone and overlapped it in the image. The single overhead camera cannot show whether it touched or passed in front.",
    teachingPoint: "Keep gloved hands between shoulder and waist level, away from the face, and adjust the mask only after re-gloving.",
  },
  "demo-3": {
    summary: "The left glove dropped below the table edge and then returned to the sterile drape.",
    teachingPoint: "Treat anything below the table edge as nonsterile; keep hands above it or re-glove before returning.",
  },
  "demo-4": {
    summary:
      "The forceps left the tray while the view was blocked and were placed back afterwards. What they touched out of view is unknown.",
    teachingPoint: "When an instrument leaves sight, treat it as possibly contaminated and set it aside instead of returning it to the tray.",
  },
};

export function demoReport(findings: Finding[]): ReviewReport {
  const count = (s: Finding["reviewStatus"]) => findings.filter((f) => f.reviewStatus === s).length;
  const keyMoments: ReportMoment[] = findings
    .filter((f) => f.reviewStatus !== "dismissed" && DEMO_REPORT_TEXT[f.eventId])
    .sort((a, b) => Number(a.reviewStatus !== "confirmed") - Number(b.reviewStatus !== "confirmed") || a.timestampSec - b.timestampSec)
    .map((f) => ({
      eventId: f.eventId,
      timestampSec: f.timestampSec,
      title: f.title,
      reviewStatus: f.reviewStatus,
      uncertainty: f.uncertainty.level,
      ...DEMO_REPORT_TEXT[f.eventId],
    }));
  return {
    source: "demo",
    generatedAt: "2026-10-18T00:00:00.000Z",
    model: "Sample text (not generated)",
    overview:
      "Four moments were flagged in this one-minute synthetic exercise. The clearest is at 00:11, when the right glove rests on the nonsterile side table and handles the forceps about four seconds later. Two others depend on what one overhead camera can see: the glove near the mask at 00:24 and the forceps carried out of view at 00:43. Watch each one before deciding.",
    keyMoments,
    coachingPoints: [
      "Three of the four moments start with a glove leaving the sterile zone: the side table, the mask and below the table edge. Keep both hands between the table edge and your shoulders while you work.",
      "If you lose sight of a glove or an instrument, assume it may be contaminated until you've checked or replaced it.",
    ],
    limitations:
      "This sample describes a synthetic clip drawn with shapes. Real reports are based on automated proposals from one camera, which can miss moments or flag ones that were fine.",
    stats: {
      findings: findings.length,
      confirmed: count("confirmed"),
      needsReview: count("needs_review"),
      dismissed: count("dismissed"),
      highUncertainty: findings.filter((f) => f.uncertainty.level === "high").length,
    },
    stale: false,
  };
}
