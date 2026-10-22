/**
 * A top-down house, drawn as furniture and rooms rather than a screenshot.
 * It is decorative on the landing page: the live simulation lives behind the
 * CTA, and the operator console shows the real state.
 */
export default function HousePreview() {
  return (
    <div className="lp-house" aria-hidden="true">
      <div className="lp-house-bar">
        <span className="lp-live">
          <span className="lp-live-dot" />
          Live simulation
        </span>
        <span className="lp-house-clock">21:42</span>
      </div>

      <div className="lp-house-plan">
        <svg viewBox="0 0 620 500" role="presentation" focusable="false">
          <rect width="620" height="500" fill="#eae3d8" />

          {/* A quiet paper grid, like a floor plan on a desk. */}
          <g stroke="#ded5c8" strokeWidth="1" opacity="0.7">
            <path d="M0 100H620M0 200H620M0 300H620M0 400H620" />
            <path d="M100 0V500M200 0V500M300 0V500M400 0V500M500 0V500" />
          </g>

          <rect x="44" y="40" width="532" height="420" fill="#f8f4ed" stroke="#26241f" strokeWidth="3" />

          {/* Interior walls. */}
          <g stroke="#37342d" strokeLinecap="square">
            <line x1="330" y1="40" x2="330" y2="270" strokeWidth="7" />
            <line x1="44" y1="270" x2="470" y2="270" strokeWidth="7" />
            <line x1="470" y1="180" x2="470" y2="460" strokeWidth="7" />
            <line x1="330" y1="180" x2="576" y2="180" strokeWidth="7" />
          </g>

          {/* Door openings, drawn over the walls. */}
          <g fill="#f8f4ed">
            <rect x="298" y="112" width="34" height="9" />
            <rect x="210" y="266" width="48" height="9" />
            <rect x="466" y="322" width="9" height="46" />
            <rect x="514" y="176" width="42" height="9" />
          </g>
          <g fill="none" stroke="#8d867b" strokeWidth="1.2">
            <path d="M298 112a34 34 0 0 1 34 30" />
            <path d="M258 270a44 44 0 0 1-44-40" />
            <path d="M470 368a46 46 0 0 1 40-46" />
            <path d="M514 180a42 42 0 0 1 38 38" />
          </g>

          {/* Living room. */}
          <g>
            <rect x="82" y="128" width="194" height="108" rx="8" fill="#e9e0d3" stroke="#d3c6b5" />
            <rect x="94" y="102" width="156" height="48" rx="10" fill="#cfc3b2" stroke="#756c60" strokeWidth="1.4" />
            <line x1="172" y1="104" x2="172" y2="148" stroke="#756c60" strokeWidth="1.2" />
            <rect x="136" y="174" width="84" height="40" rx="4" fill="#b9a78e" />
            <rect x="246" y="164" width="44" height="48" rx="9" fill="#d9cab7" stroke="#8c8173" strokeWidth="1.2" />
            <circle cx="64" cy="64" r="14" fill="#465907" opacity="0.85" />
            <rect x="58" y="74" width="12" height="14" rx="3" fill="#a77b57" />
            <rect x="54" y="228" width="34" height="22" rx="3" fill="#b6a48c" />
            <text x="180" y="96" className="lp-room-label">LIVING</text>
          </g>

          {/* Kitchen. */}
          <g>
            <rect x="348" y="52" width="210" height="38" fill="#d8d0c3" stroke="#9b9285" strokeWidth="1.2" />
            <rect x="380" y="106" width="126" height="36" rx="3" fill="#c9bdac" stroke="#9b9285" strokeWidth="1.2" />
            <circle cx="386" cy="71" r="10" fill="none" stroke="#7e7568" strokeWidth="1.4" />
            <circle cx="386" cy="71" r="3" fill="#7e7568" />
            <g fill="none" stroke="#7e7568" strokeWidth="1.2">
              <circle cx="452" cy="62" r="6" />
              <circle cx="470" cy="62" r="6" />
              <circle cx="452" cy="80" r="6" />
              <circle cx="470" cy="80" r="6" />
            </g>
            <rect x="512" y="58" width="26" height="26" rx="3" fill="#e6dfd4" stroke="#7e7568" />
            <text x="455" y="166" className="lp-room-label">KITCHEN</text>
          </g>

          {/* Bath. */}
          <g>
            <rect x="348" y="200" width="92" height="34" rx="15" fill="#f3f0ea" stroke="#9b9285" strokeWidth="1.4" />
            <circle cx="364" cy="217" r="2" fill="#9b9285" />
            <rect x="348" y="241" width="46" height="18" rx="2" fill="#d8d0c3" stroke="#9b9285" />
            <circle cx="371" cy="250" r="5" fill="none" stroke="#7e7568" />
            <text x="407" y="232" className="lp-room-label">BATH</text>
          </g>

          {/* Bedroom. */}
          <g>
            <rect x="84" y="316" width="164" height="112" rx="9" fill="#ded4c5" stroke="#8c8173" strokeWidth="1.4" />
            <rect x="94" y="326" width="54" height="18" rx="5" fill="#f4efe7" />
            <rect x="158" y="326" width="54" height="18" rx="5" fill="#f4efe7" />
            <rect x="84" y="352" width="164" height="76" rx="6" fill="#c9bba6" />
            <rect x="66" y="322" width="14" height="34" rx="2" fill="#b6a48c" />
            <rect x="252" y="322" width="14" height="34" rx="2" fill="#b6a48c" />
            <rect x="300" y="304" width="146" height="40" rx="3" fill="#d8d0c3" stroke="#9b9285" strokeWidth="1.2" />
            <line x1="300" y1="324" x2="446" y2="324" stroke="#9b9285" strokeWidth="1" />
            <text x="180" y="306" className="lp-room-label">BEDROOM</text>
          </g>

          {/* Hall. */}
          <g>
            <rect x="494" y="292" width="54" height="20" rx="2" fill="#c9bdac" stroke="#9b9285" />
            <circle cx="522" cy="330" r="3" fill="#8d867b" />
            <text x="522" y="244" className="lp-room-label lp-room-label-vertical" transform="rotate(90 522 244)">HALL</text>
          </g>

          {/* Active devices. The outer rings are the only moving pixels. */}
          <g className="lp-device lp-device-one">
            <circle cx="66" cy="204" r="18" fill="#e75800" opacity="0.12" />
            <circle cx="66" cy="204" r="5" fill="#e75800" />
          </g>
          <g className="lp-device lp-device-two">
            <circle cx="540" cy="140" r="18" fill="#e75800" opacity="0.12" />
            <circle cx="540" cy="140" r="5" fill="#e75800" />
          </g>
          <g className="lp-device lp-device-three">
            <circle cx="330" cy="236" r="18" fill="#465907" opacity="0.14" />
            <circle cx="330" cy="236" r="5" fill="#465907" />
          </g>
        </svg>
      </div>

      <div className="lp-house-footer">
        <div>
          <span>Lights</span>
          <strong>30%</strong>
        </div>
        <div>
          <span>Climate</span>
          <strong>21.0°</strong>
        </div>
        <div>
          <span>Bookings</span>
          <strong>1</strong>
        </div>
        <div>
          <span>Timers</span>
          <strong>1</strong>
        </div>
      </div>
    </div>
  );
}
