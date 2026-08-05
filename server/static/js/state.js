let accessToken = null;
let tokenProvider = null;

export function setAccessToken(token) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

// auth.js가 "지금 유효한 토큰을 가져오는 함수"를 여기에 등록한다.
// state.js가 auth.js를 직접 import하면 순환 참조가 되므로 주입 방식으로 둔다.
export function setTokenProvider(fn) {
  tokenProvider = fn;
}

// Supabase access token은 기본 1시간이면 만료된다. supabase-js가 백그라운드에서
// 알아서 갱신하지만, 로그인 시점에 붙잡아둔 값을 계속 쓰면 그 갱신이 반영되지
// 않아 페이지를 오래 열어둔 뒤부터 모든 API 호출이 401이 된다(실제로 발생했다 -
// 진행률 폴링이 연속 401을 냈다). 그래서 매 호출마다 현재 세션에서 토큰을 다시
// 받는다. getSession()은 평소엔 로컬 저장소만 읽고 만료가 임박했을 때만
// 네트워크로 갱신하므로 매번 불러도 부담이 없다.
export async function apiHeaders() {
  if (tokenProvider) {
    const fresh = await tokenProvider();
    if (fresh) accessToken = fresh;
  }
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${accessToken}`,
  };
}
