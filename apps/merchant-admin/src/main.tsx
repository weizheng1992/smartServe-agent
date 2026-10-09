import React from 'react';
import ReactDOM from 'react-dom/client';
import 'ui/src/styles/globals.css';
// 站点主题覆盖必须在 ui globals 之后引入(:root 同特异性后者胜)
import './styles/theme.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
