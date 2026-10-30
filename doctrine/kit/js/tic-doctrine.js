// The Intelligence Company doctrine kit, browser module (ES module, no dependencies).
// Likelihood terms, confidence chips, lifeline statuses and response ladders for
// every program's pages and for COP. The vocabulary block below is generated from
// vocab/*.json by tools/build_js.py; edit the JSON, not this block.
//
// Rules the display must keep:
// - Store the number; show the ICD 203 term with its band ("Likely (55-80%)").
// - Likelihood and confidence are two separate chips, never one sentence.
// - Grey means no data, never quiet.

// BEGIN GENERATED VOCAB
export const VOCAB = {
  "version": {
    "likelihood": "1.0",
    "confidence": "1.0"
  },
  "likelihood": [
    {
      "id": "almost_no_chance",
      "step": 0,
      "term": "Almost no chance",
      "synonym": "Remote",
      "lower": 0.01,
      "upper": 0.05,
      "band_label": "01-05%",
      "uk": {
        "term": "Remote chance",
        "band_label": ">0-~5%"
      }
    },
    {
      "id": "very_unlikely",
      "step": 1,
      "term": "Very unlikely",
      "synonym": "Highly improbable",
      "lower": 0.05,
      "upper": 0.2,
      "band_label": "05-20%",
      "uk": {
        "term": "Highly unlikely",
        "band_label": "~10-~20%"
      }
    },
    {
      "id": "unlikely",
      "step": 2,
      "term": "Unlikely",
      "synonym": "Improbable",
      "lower": 0.2,
      "upper": 0.45,
      "band_label": "20-45%",
      "uk": {
        "term": "Unlikely",
        "band_label": "~25-~35%"
      }
    },
    {
      "id": "roughly_even_chance",
      "step": 3,
      "term": "Roughly even chance",
      "synonym": "Roughly even odds",
      "lower": 0.45,
      "upper": 0.55,
      "band_label": "45-55%",
      "uk": {
        "term": "Realistic possibility (no exact equivalent)",
        "band_label": "~40-<50%"
      }
    },
    {
      "id": "likely",
      "step": 4,
      "term": "Likely",
      "synonym": "Probable",
      "lower": 0.55,
      "upper": 0.8,
      "band_label": "55-80%",
      "uk": {
        "term": "Likely or probable",
        "band_label": "~55-~75%"
      }
    },
    {
      "id": "very_likely",
      "step": 5,
      "term": "Very likely",
      "synonym": "Highly probable",
      "lower": 0.8,
      "upper": 0.95,
      "band_label": "80-95%",
      "uk": {
        "term": "Highly likely",
        "band_label": "~80-~90%"
      }
    },
    {
      "id": "almost_certain",
      "step": 6,
      "term": "Almost certain",
      "synonym": "Nearly certain",
      "lower": 0.95,
      "upper": 0.99,
      "band_label": "95-99%",
      "uk": {
        "term": "Almost certain",
        "band_label": "~95-<100%"
      }
    }
  ],
  "confidence": {
    "low": {
      "term": "Low",
      "meaning": "Information is scant, questionable, fragmented or old, or rests on one line of evidence; the judgment could change sharply."
    },
    "moderate": {
      "term": "Moderate",
      "meaning": "Two or more independent lines of evidence agree, with gaps, caveats or assumptions that keep it short of high."
    },
    "high": {
      "term": "High",
      "meaning": "Three or more independent lines agree, few gaps or assumptions, low deception potential, alternatives examined, and a method with a scored track record. Not a certainty."
    }
  },
  "confidence_label": "Rule-based, not statistical",
  "lifeline_status": {
    "unknown": {
      "term": "Unknown",
      "letter": "U",
      "rgb": [
        145,
        147,
        149
      ],
      "hex": "#919395",
      "meaning": "Extent of disruption unknown. Also used when the suite has no data."
    },
    "significant": {
      "term": "Significant impact",
      "letter": "S",
      "rgb": [
        197,
        32,
        56
      ],
      "hex": "#C52038",
      "meaning": "Severe challenges hindering essential services."
    },
    "moderate": {
      "term": "Moderate impact",
      "letter": "M",
      "rgb": [
        251,
        186,
        22
      ],
      "hex": "#FBBA16",
      "meaning": "Disruption to normal pre-incident service; restoration in progress or by temporary means."
    },
    "minimal": {
      "term": "Minimal impact",
      "letter": "OK",
      "rgb": [
        94,
        156,
        66
      ],
      "hex": "#5E9C42",
      "meaning": "Functioning at pre-incident levels, minor disruptions only."
    },
    "baseline": {
      "term": "Administrative / pre-incident",
      "letter": "B",
      "rgb": [
        1,
        82,
        135
      ],
      "hex": "#015287",
      "meaning": "Not an operational status; pre-incident state or no incident."
    }
  },
  "lifelines": {
    "safety_and_security": {
      "name": "Safety and Security",
      "abbr": "SS"
    },
    "food_hydration_shelter": {
      "name": "Food, Hydration, Shelter",
      "abbr": "FHS"
    },
    "health_and_medical": {
      "name": "Health and Medical",
      "abbr": "HM"
    },
    "energy": {
      "name": "Energy",
      "abbr": "E"
    },
    "communications": {
      "name": "Communications",
      "abbr": "C"
    },
    "transportation": {
      "name": "Transportation",
      "abbr": "T"
    },
    "hazardous_materials": {
      "name": "Hazardous Materials",
      "abbr": "HZ"
    },
    "water_systems": {
      "name": "Water Systems",
      "abbr": "W"
    }
  },
  "ladders": {
    "pager": {
      "name": "USGS PAGER earthquake alert",
      "values": {
        "green": {
          "severity": 0,
          "meaning": "No response needed (estimated fatalities 0; losses under US$1M)."
        },
        "yellow": {
          "severity": 2,
          "meaning": "Local or regional response (fatalities 1-99; losses US$1M-100M)."
        },
        "orange": {
          "severity": 3,
          "meaning": "National response (fatalities 100-999; losses US$100M-1B)."
        },
        "red": {
          "severity": 4,
          "meaning": "International response (fatalities 1,000+; losses US$1B+)."
        }
      }
    },
    "gdacs": {
      "name": "GDACS alert level",
      "values": {
        "green": {
          "severity": 0,
          "meaning": "Low humanitarian impact expected."
        },
        "orange": {
          "severity": 3,
          "meaning": "Moderate impact; international assistance may be needed."
        },
        "red": {
          "severity": 4,
          "meaning": "Severe impact; international assistance likely needed."
        }
      }
    },
    "cems": {
      "name": "Copernicus Emergency Management Service rapid mapping",
      "values": {
        "activated": {
          "severity": 3,
          "meaning": "Rapid mapping activated for the event."
        },
        "closed": {
          "severity": 1,
          "meaning": "Activation closed."
        }
      }
    },
    "ifrc": {
      "name": "IFRC GO response",
      "values": {
        "dref": {
          "severity": 2,
          "meaning": "Disaster Response Emergency Fund allocation."
        },
        "emergency_appeal": {
          "severity": 3,
          "meaning": "Emergency Appeal launched."
        }
      }
    },
    "easa_czib": {
      "name": "EASA Conflict Zone Information Bulletin",
      "values": {
        "active": {
          "severity": 3,
          "meaning": "Bulletin in force for the airspace."
        },
        "expired": {
          "severity": 0,
          "meaning": "Bulletin lapsed or withdrawn."
        }
      }
    },
    "state_travel_advisory": {
      "name": "US State Department Travel Advisory level",
      "values": {
        "level_1": {
          "severity": 0,
          "meaning": "Exercise normal precautions."
        },
        "level_2": {
          "severity": 1,
          "meaning": "Exercise increased caution."
        },
        "level_3": {
          "severity": 2,
          "meaning": "Reconsider travel."
        },
        "level_4": {
          "severity": 4,
          "meaning": "Do not travel."
        }
      }
    },
    "state_post_posture": {
      "name": "US embassy or consulate staffing posture",
      "values": {
        "normal": {
          "severity": 0,
          "meaning": "Normal operations."
        },
        "authorized_departure": {
          "severity": 2,
          "meaning": "Non-emergency staff and family members may leave at government expense."
        },
        "ordered_departure": {
          "severity": 3,
          "meaning": "Non-emergency staff and family members are ordered to leave."
        },
        "suspended_operations": {
          "severity": 4,
          "meaning": "The post has suspended operations."
        }
      }
    }
  }
};
// END GENERATED VOCAB

/** ICD 203 term object for probability p (0 to 1); band edges resolved symmetrically about 0.5. */
export function termFor(p) {
  if (typeof p !== "number" || !(p >= 0 && p <= 1)) throw new RangeError(`probability must be 0 to 1, got ${p}`);
  const t = VOCAB.likelihood;
  if (p < 0.05) return t[0];
  if (p < 0.2) return t[1];
  if (p < 0.45) return t[2];
  if (p <= 0.55) return t[3];
  if (p <= 0.8) return t[4];
  if (p <= 0.95) return t[5];
  return t[6];
}

/** "Likely (55-80%)" */
export function likelihoodLabel(p) {
  const t = termFor(p);
  return `${t.term} (${t.band_label})`;
}

/** UK yardstick equivalent, for a tooltip. */
export function ukTooltip(p) {
  const t = termFor(p);
  return `UK yardstick: ${t.uk.term} (${t.uk.band_label})`;
}

const EDGE = { high: "solid", moderate: "dashed", low: "dotted" };

/** Confidence chip: {text, meaning, edge}. Shown apart from the likelihood chip. */
export function confidenceChip(level) {
  const c = VOCAB.confidence[level];
  if (!c) throw new RangeError(`unknown confidence level ${level}`);
  return { text: `Confidence: ${c.term}`, meaning: c.meaning, edge: EDGE[level], label: VOCAB.confidence_label };
}

/** Two chips for one judgment, never joined into one sentence. */
export function judgmentChips(item) {
  const chips = [];
  if (typeof item.probability === "number") {
    const t = termFor(item.probability);
    chips.push({ kind: "likelihood", text: likelihoodLabel(item.probability), step: t.step, tooltip: ukTooltip(item.probability) });
  }
  if (item.confidence) chips.push({ kind: "confidence", ...confidenceChip(item.confidence) });
  return chips;
}

/** FEMA lifeline status: {term, letter, hex, meaning}. Unknown status is grey. */
export function lifelineStatus(status) {
  return VOCAB.lifeline_status[status] || VOCAB.lifeline_status.unknown;
}

/** A response ladder rung from "ladder:value", e.g. "pager:orange". */
export function ladderRung(stage) {
  const [ladder, value] = String(stage).split(":");
  const l = VOCAB.ladders[ladder];
  if (!l || !l.values[value]) return null;
  return { ladder: l.name, value, ...l.values[value] };
}

const ARROWS = { new: "✦", raised: "↑", lowered: "↓", unchanged: "→", changed: "⇄", withdrawn: "✕" };

/** Change since the last assessment, as an arrow plus words. */
export function changeText(item, priorProbability) {
  const c = item.change_from_prior;
  if (!c) return null;
  let words = { new: "New", raised: "Up", lowered: "Down", unchanged: "Unchanged", changed: "Changed", withdrawn: "Withdrawn" }[c];
  if ((c === "raised" || c === "lowered") && typeof priorProbability === "number" && typeof item.probability === "number") {
    words += ` from ${termFor(priorProbability).term} to ${termFor(item.probability).term}`;
  }
  return { arrow: ARROWS[c], text: words };
}

/** Indicator state for drawing: no data is grey and hatched, never blank. */
export function indicatorStyle(state) {
  return {
    present: { label: "Present", fill: "solid" },
    absent: { label: "Absent", fill: "outline" },
    no_data: { label: "No data", fill: "hatched", grey: true },
  }[state] || { label: "No data", fill: "hatched", grey: true };
}
