import { useId } from "react";
import { cn } from "@/lib/format";

/**
 * Sherlog, the Opscend mascot: a small bird in a deerstalker who reads the logs
 * and finds the commit. Flat colours only, so it sits on the matte landing theme
 * and on the console alike.
 *
 * The magnifying glass sways; the eyes do not. The big eye is what the lens shows,
 * so it is drawn in place and clipped to wherever the lens currently is.
 * `mood="alert"` makes Sherlog hop and lean in, for the moment something fails.
 */
export function Sherlog({
  size = 120,
  animated = true,
  mood = "calm",
  className,
  title = "Sherlog, the Opscend mascot",
}: {
  size?: number;
  animated?: boolean;
  mood?: "calm" | "alert";
  className?: string;
  title?: string;
}) {
  const lens = useId();
  const pivot = { transformOrigin: "166px 150px" }; // where the wing grips the handle
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 200 200"
      fill="none"
      role="img"
      aria-label={title}
      className={cn("overflow-visible", animated && "sherlog", animated && mood === "alert" && "sherlog-alert", className)}
    >
      <defs>
        <clipPath id={lens}>
          <circle className="sherlog-glass" style={pivot} cx="130" cy="106" r="19.5" />
        </clipPath>
      </defs>

      <g className="sherlog-hop">
        <path d="M52 150 30 168l30-2z" fill="#cfc9bb" />
        <g stroke="#d4522a" strokeWidth="5" strokeLinecap="round">
          <path d="M86 170v14m0 0-8 5m8-5 8 5" />
          <path d="M116 170v14m0 0-8 5m8-5 8 5" />
        </g>
        <g className="sherlog-body">
          <path d="M100 62c33 0 54 24 54 58s-21 56-54 56-54-22-54-56 21-58 54-58z" fill="#e6e1d6" />
          <path d="M58 118c2 22 12 36 26 40-16-2-32-14-32-36 0-6 2-9 6-4z" fill="#cfc9bb" />
          <path d="M56 112c0 26 12 42 30 46-22 0-36-16-36-40 0-8 3-10 6-6z" fill="#cfc9bb" />
          {/* deerstalker */}
          <path d="M40 86c6-8 16-10 24-8l-4 12c-8 0-14 0-20-4z" fill="#6f6a60" />
          <path d="M56 86c0-28 20-46 44-46s44 18 44 46c-28-8-60-8-88 0z" fill="#8f8a7e" />
          <path d="M100 40v40M78 46c-6 10-9 22-9 36M122 46c6 10 9 22 9 36" stroke="#6f6a60" strokeWidth="2.5" />
          <path d="M138 78c10-2 20 0 26 8-8 4-16 4-26 4z" fill="#6f6a60" />
          <rect x="86" y="30" width="28" height="13" rx="6.5" fill="#6f6a60" />
          <circle cx="100" cy="36.5" r="3" fill="#e6e1d6" />

          {/* both eyes belong to the head and stay put */}
          <g className="sherlog-eye" style={{ transformOrigin: "80px 108px" }}>
            <circle cx="80" cy="108" r="6.5" fill="#0f0f0e" />
            <circle cx="82" cy="106" r="2" fill="#e6e1d6" />
          </g>
          <g className="sherlog-eye" style={{ transformOrigin: "124px 108px" }}>
            <circle cx="124" cy="108" r="6.5" fill="#0f0f0e" />
            <circle cx="126" cy="106" r="2" fill="#e6e1d6" />
          </g>
          <path d="M94 116h18l-9 13z" fill="#d4522a" />

          {/* the glass: handle and lens sway together */}
          <g className="sherlog-glass" style={pivot}>
            <path d="m146 124 22 26" stroke="#6f6a60" strokeWidth="9" strokeLinecap="round" />
            <circle cx="130" cy="106" r="22" fill="#f6f3ec" />
          </g>
          {/* what the lens shows: the same eye, enlarged, visible only through the lens */}
          <g clipPath={`url(#${lens})`}>
            <g className="sherlog-eye" style={{ transformOrigin: "127px 107px" }}>
              <circle cx="127" cy="107" r="11" fill="#0f0f0e" />
              <circle cx="130.5" cy="103.5" r="3.5" fill="#f6f3ec" />
            </g>
          </g>
          <circle className="sherlog-glass" style={pivot} cx="130" cy="106" r="22" stroke="#d4522a" strokeWidth="6" />

          <path d="M150 138c8-2 16 2 16 10s-10 12-18 6z" fill="#cfc9bb" />
        </g>
      </g>
    </svg>
  );
}
