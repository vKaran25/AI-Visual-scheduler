// The API is served from the same origin as the pages, so paths are relative.
window.API_BASE_URL = '';
window.LOGIN_URL = '/home';
window.PLANNER_URL = '/';
window.calendarNow = function(){
  const zone = typeof currentUser !== 'undefined' && currentUser ? currentUser.timezone : undefined;
  return zone ? new Date(new Date().toLocaleString('en-US',{timeZone:zone})) : new Date();
};
