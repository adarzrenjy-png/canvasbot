import type { MeshFace, MeshPayload } from "../api";

function bytes(b64: string): ArrayBuffer {
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

export interface DecodedMesh {
  positions: Float32Array;
  indices: Uint32Array;
  edges: Float32Array;
  faces: MeshFace[];
  /** Vertex range [first, last] owned by each face; faces never share vertices. */
  faceVertices: [number, number][];
  /** Triangle index at which each face starts, for picking. */
  faceTriStart: number[];
}

export function decodeMesh(payload: MeshPayload): DecodedMesh {
  const positions = new Float32Array(bytes(payload.positions));
  const indices = new Uint32Array(bytes(payload.indices));
  const edges = payload.edges ? new Float32Array(bytes(payload.edges)) : new Float32Array();
  const faceVertices: [number, number][] = [];
  const faceTriStart: number[] = [];
  for (const face of payload.faces) {
    let lo = Infinity;
    let hi = -1;
    for (let i = face.start; i < face.start + face.count; i++) {
      const v = indices[i];
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    faceVertices.push(hi < 0 ? [0, -1] : [lo, hi]);
    faceTriStart.push(face.start / 3);
  }
  return { positions, indices, edges, faces: payload.faces, faceVertices, faceTriStart };
}

/** Which face (by index) does triangle `tri` belong to? Binary search over starts. */
export function faceOfTriangle(mesh: DecodedMesh, tri: number): number {
  let lo = 0;
  let hi = mesh.faceTriStart.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (mesh.faceTriStart[mid] <= tri) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}
